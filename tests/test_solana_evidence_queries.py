from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable,FinalizedRecord
from meme_machine.solana_evidence_queries import PumpEvidenceView,MeteoraEvidenceView
from tests.test_solana_evidence_plane import proof,record,ENDPOINT

class LocalQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.writer=EvidenceWriter(Path(self.temp.name)/'db')
        self.reader=EvidenceReader(self.writer.path)
    def tearDown(self):self.reader.close();self.writer.close();self.temp.cleanup()

    def test_pump_local_event_exact_payload_and_no_rpc_dependency(self):
        event={'slot':10,'market_time':10,'pool':'pool','buy':True,'wallet':'wallet','amount':12}
        self.writer.ingest([replace(record(),payload={'event':event})],proof=proof())
        view=PumpEvidenceView(self.reader,'pump')
        result=view.events('pool',lower_slot=10,upper_slot=10,lower_time=9,upper_time=11,as_of=100)
        self.assertEqual(result,[event])
        self.assertEqual(view.telemetry()['foreground_historical_rpc_count'],0)
        self.assertEqual(view.telemetry()['decisions_fully_local'],1)

    def test_pump_gap_never_falls_back(self):
        view=PumpEvidenceView(self.reader,'pump')
        with self.assertRaises(EvidenceUnavailable):view.events('pool',lower_slot=10,upper_slot=12,lower_time=9,upper_time=12,as_of=100)
        self.assertEqual(view.telemetry()['decisions_blocked_by_gaps'],1)
        self.assertEqual(view.foreground_historical_rpc,0)

    def test_meteora_local_preserves_transaction_bodies_order_and_witness(self):
        transactions=[];records=[]
        for slot in (10,11,12):
            tx=dict(slot=slot,blockTime=slot,transactionIndex=3,
                transaction={'signatures':['sig'+str(slot)],'message':{'accountKeys':['pool']}},meta={'err':None})
            transactions.append(tx)
            records.append(FinalizedRecord('tx'+str(slot),'meteora',slot,'sig'+str(slot),'program',('pool',),slot,tx,
                'alchemy_finalized_stream',ENDPOINT,100,transaction_index=3,kind='transaction'))
        self.writer.ingest(records,proof=proof(10,12,scope='meteora'))
        view=MeteoraEvidenceView(self.reader,'meteora')
        signatures,bodies,metadata=view.interval('pool',start_slot=10,end_slot=12,as_of=100)
        self.assertEqual([s['slot'] for s in signatures],[12,11,10])
        self.assertEqual(bodies,{'sig11':transactions[1],'sig12':transactions[2]})
        self.assertEqual(metadata['historical_provider_calls'],0)

    def test_meteora_does_not_manufacture_boundary(self):
        self.writer.ingest([],proof=proof(10,12,scope='meteora'))
        with self.assertRaisesRegex(EvidenceUnavailable,'boundary'):
            MeteoraEvidenceView(self.reader,'meteora').interval('pool',start_slot=10,end_slot=12,as_of=100)

    def test_meteora_boundary_is_scoped_to_requested_pool(self):
        records=[]
        for pool,slot in [('pool',8),('other',10),('pool',12)]:
            tx=dict(slot=slot,blockTime=slot,transactionIndex=1,
                transaction={'signatures':['sig'+str(slot)]},meta={'err':None})
            records.append(FinalizedRecord('tx'+str(slot),'meteora',slot,'sig'+str(slot),
                'program',(pool,),slot,tx,'alchemy_finalized_stream',ENDPOINT,100,
                transaction_index=1,kind='transaction'))
        self.writer.ingest(records,proof=proof(8,12,scope='meteora'))
        signatures,_,_=MeteoraEvidenceView(self.reader,'meteora').interval(
            'pool',start_slot=10,end_slot=12,as_of=100)
        self.assertEqual([s['slot'] for s in signatures],[12,8])
