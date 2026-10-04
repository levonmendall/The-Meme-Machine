from dataclasses import replace
import tempfile
from pathlib import Path
import unittest

from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable
from meme_machine.solana_evidence_transport import Subscription,alchemy_stream_endpoint,FinalizedNotificationDecoder,AddressGapRepair

ENDPOINT='a'*64

def tx(n=10):
    return dict(slot=n,blockTime=10,transactionIndex=1,
                transaction={'signatures':['sig'+str(n)],'message':{}},meta={'err':None})

class RPC:
    def __init__(self,pages):self.pages=iter(pages);self.calls=[]
    def call(self,method,params,priority):
        self.calls.append((method,params,priority));return next(self.pages)

class TransportTests(unittest.TestCase):
    def test_endpoint_uses_same_app_and_rejects_other_hosts(self):
        self.assertEqual(alchemy_stream_endpoint('https://solana-mainnet.g.alchemy.com/v2/offline-test'),
                         'wss://solana-mainnet.streaming.alchemy.com/v2/offline-test')
        for url in ('https://api.mainnet-beta.solana.com','https://example.com/v2/offline-test',
                    'https://solana-mainnet.g.alchemy.com/v2/offline-test?x=1'):
            with self.assertRaises(EvidenceUnavailable):alchemy_stream_endpoint(url)

    def test_subscriptions_filtered_finalized_never_all(self):
        for kind,method in [('logs','logsSubscribe'),('account','accountSubscribe'),('transactions','blockSubscribe')]:
            request=Subscription('pump','scope','pool',kind,1).request(1)
            self.assertEqual(request['method'],method)
            self.assertEqual(request['params'][1]['commitment'],'finalized')
            self.assertNotEqual(request['params'][0],'all')

    def test_filtered_array_rank_never_fabricates_chain_index(self):
        sub=Subscription('meteora','meteora:pool','pool','transactions',0)
        body=tx();del body['transactionIndex']
        message={'method':'blockNotification','params':{'result':{'value':{
            'slot':10,'err':None,'block':{'blockTime':10,'transactions':[body]}}}}}
        rows=FinalizedNotificationDecoder(endpoint_identity=ENDPOINT).decode(sub,message,100)
        self.assertIsNone(rows[0].transaction_index)
        self.assertEqual(rows[0].payload['transaction'],body['transaction'])

    def test_truncated_logs_rejected(self):
        decoder=FinalizedNotificationDecoder(endpoint_identity=ENDPOINT,log_decoder=lambda _:[])
        sub=Subscription('pump','pump','program','logs',4)
        message={'method':'logsNotification','params':{'result':{'context':{'slot':10},'value':{
            'signature':'sig','logs':['Log truncated'],'err':None}}}}
        with self.assertRaises(EvidenceUnavailable):decoder.decode(sub,message,100)

    def test_bounded_repair_cursor_restart_and_late_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db';writer=EvidenceWriter(path,clock=lambda:100)
            writer.gap('meteora:pool',10,12)
            rpc=RPC([{'data':[tx(10)],'paginationToken':'page2'}, {'data':[tx(11)],'paginationToken':None}])
            repair=AddressGapRepair(rpc,writer,endpoint_identity=ENDPOINT)
            self.assertFalse(repair.step(1,'pool',finalized_through=12,now=110)['complete'])
            writer.close();writer=EvidenceWriter(path,clock=lambda:111)
            repair=AddressGapRepair(rpc,writer,endpoint_identity=ENDPOINT)
            self.assertTrue(repair.step(1,'pool',finalized_through=12,now=120)['complete'])
            reader=EvidenceReader(path)
            # Writer restart creates an independent open-ended discontinuity. The
            # exact repaired gap is resolved, but unknown future coverage is not.
            self.assertFalse(reader.covered('meteora:pool',10,12,as_of=115))
            self.assertEqual(writer.db.execute('SELECT pages,repaired FROM gaps WHERE id=1').fetchone(),(2,120))
            self.assertEqual(rpc.calls[1][1][1]['paginationToken'],'page2')
            self.assertTrue(all(c[0]=='getTransactionsForAddress' and c[2] is False for c in rpc.calls))
            reader.close();writer.close()

    def test_malformed_repair_page_does_not_advance_cursor(self):
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db',clock=lambda:100);writer.gap('meteora:pool',10,12)
            bad=tx();del bad['transactionIndex']
            repair=AddressGapRepair(RPC([{'data':[bad]}]),writer,endpoint_identity=ENDPOINT)
            with self.assertRaises(EvidenceUnavailable):repair.step(1,'pool',finalized_through=12,now=110)
            self.assertEqual(writer.db.execute('SELECT pages FROM gaps').fetchone()[0],0)
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
            writer.close()

    def test_empty_exact_range_can_be_verified_without_fake_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db',clock=lambda:100);writer.gap('scope',10,12)
            repair=AddressGapRepair(RPC([{'data':[],'paginationToken':None}]),writer,endpoint_identity=ENDPOINT)
            repair.step(1,'pool',finalized_through=12,now=110)
            reader=EvidenceReader(writer.path)
            self.assertEqual(reader.window('scope',10,12,as_of=110),[])
            reader.close();writer.close()

    def test_reused_signature_across_slots_does_not_overwrite_event(self):
        decoder=FinalizedNotificationDecoder(endpoint_identity=ENDPOINT,
            log_decoder=lambda tx:[dict(index=0,slot=tx['slot'],mint='mint',market_time=10)])
        sub=Subscription('pump','pump','program','logs',4)
        def message(slot):
            return {'method':'logsNotification','params':{'result':{'context':{'slot':slot},
                'value':{'signature':'reused','logs':[],'err':None}}}}
        first=decoder.decode(sub,message(10),100)[0]
        second=decoder.decode(sub,message(11),100)[0]
        self.assertNotEqual(first.identity,second.identity)
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db')
            writer.ingest([first,second])
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],2)
            writer.close()
