import tempfile
from pathlib import Path
import unittest
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_evidence_service import FinalizedFence

class FenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.writer=EvidenceWriter(Path(self.temp.name)/'db',clock=lambda:100)
        self.fence=FinalizedFence(self.writer,endpoint_identity='a'*64,decoders={'pump':lambda _:[]})
        self.reader=EvidenceReader(self.writer.path);self.sub=Subscription('service','pump','program','census',4)
    def tearDown(self):self.reader.close();self.writer.close();self.temp.cleanup()
    def block(self,slot,parent,seen=100):
        value=dict(slot=slot,err=None,block=dict(parentSlot=parent,blockhash=f'h{slot}',previousBlockhash=f'h{parent}',blockTime=slot,transactions=[dict(transaction=dict(signatures=[f's{slot}'],message=dict(accountKeys=['program'])),meta=dict(logMessages=[],err=None))]))
        self.fence.block(self.sub,{'params':{'result':{'value':value}}},seen)
    def log(self,slot,seen=100):
        msg={'method':'logsNotification','params':{'result':{'context':{'slot':slot},'value':{'signature':f's{slot}','logs':[],'err':None}}}}
        self.fence.logs(Subscription('service','pump','program','logs',4),msg,seen)
    def test_single_notification_and_silence_never_grant_coverage(self):
        self.log(10);self.block(10,9)
        self.assertFalse(self.reader.covered('pump',10,10,as_of=10000))
    def test_complete_census_and_linked_child_seal_exact_interval(self):
        self.log(10);self.block(10,9);self.block(12,10)
        self.assertTrue(self.reader.covered('pump',10,11,as_of=100))
        self.assertFalse(self.reader.covered('pump',12,12,as_of=100))
    def test_missing_filtered_delivery_fails_closed_and_preserves_asof(self):
        self.block(10,9);self.block(11,10)
        self.assertFalse(self.reader.covered('pump',10,10,as_of=100))
        self.assertEqual(self.reader.telemetry()['unresolved_gaps'],1)
        self.log(10,110)
        self.assertFalse(self.reader.covered('pump',10,10,as_of=105))
        self.assertTrue(self.reader.covered('pump',10,10,as_of=110))
    def test_unknown_parent_is_explicit_gap_not_filtered_silence(self):
        self.log(10);self.block(10,9);self.log(12);self.block(12,11);self.block(13,12)
        self.assertFalse(self.reader.covered('pump',10,11,as_of=100))
        self.assertTrue(self.reader.covered('pump',12,12,as_of=100))
    def test_disconnect_cannot_bridge_sessions(self):
        self.log(10);self.block(10,9);self.fence.disconnect();self.block(11,10)
        self.assertFalse(self.reader.covered('pump',10,10,as_of=100))
    def test_consumer_cannot_submit_proof_or_modify_evidence(self):
        for op in ['ingest','coverage','repair','frontier','sql']:
            with self.assertRaises(EvidenceUnavailable):self.fence.command({'op':op})
    def test_restart_does_not_turn_old_receipt_into_live_coverage(self):
        self.log(10);self.block(10,9);path=self.writer.path
        self.writer.close();self.writer=EvidenceWriter(path,clock=lambda:100)
        self.fence=FinalizedFence(self.writer,endpoint_identity='a'*64,decoders={'pump':lambda _:[]})
        self.block(11,10)
        self.assertFalse(self.reader.covered('pump',10,10,as_of=100))

    def test_interest_ownership_lease_and_lifecycle_downgrade(self):
        def interest(owner,consumer,lifecycle='candidate',priority=3):
            self.fence.command(dict(op='interest',owner=owner,consumer=consumer,scope='pump',
                lower_slot=10,priority=priority,lifecycle=lifecycle,addresses=['shared-account']))
        interest('position','pump','reserved',1)
        interest('candidate','meteora')
        with self.assertRaises(EvidenceUnavailable):
            self.fence.command(dict(op='release',consumer='meteora',owner='position',scope='pump',resolved=True))
        with self.assertRaises(EvidenceUnavailable):interest('position','pump')
        self.fence.expire_candidates(1401)
        self.assertEqual(self.writer.db.execute("SELECT active FROM interests WHERE owner='candidate'").fetchone()[0],0)
        self.assertEqual(self.writer.db.execute("SELECT active FROM interests WHERE owner='position'").fetchone()[0],1)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM service_interests').fetchone()[0],1)
        self.fence.health('phase','DRAINING')
        with self.assertRaises(EvidenceUnavailable):interest('new','pump')
        interest('position','pump','open',0)
        self.fence.command(dict(op='release',consumer='pump',owner='position',scope='pump',resolved=True))

    def test_subscription_growth_is_rejected_before_partial_interest_commit(self):
        for i in range(256):
            self.fence.command(dict(op='interest',owner=str(i),scope='pump',lower_slot=10,
                priority=3,lifecycle='candidate',addresses=['a'+str(i)]))
        with self.assertRaises(EvidenceUnavailable):
            self.fence.command(dict(op='interest',owner='overflow',scope='pump',lower_slot=10,
                priority=3,lifecycle='candidate',addresses=['overflow']))
        self.assertIsNone(self.writer.db.execute("SELECT 1 FROM interests WHERE owner='overflow'").fetchone())
