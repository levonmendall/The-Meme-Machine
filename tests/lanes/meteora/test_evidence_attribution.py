import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.lanes.meteora.solana_evidence_broker import EvidenceBroker

class AttributionTests(unittest.TestCase):
    def test_cross_lane_counts_preserve_original_deadline_and_history(self):
        with tempfile.TemporaryDirectory() as d:
            now=[100.]
            broker=EvidenceBroker(str(Path(d)/'e.db'),clock=lambda:now[0],sleeper=lambda _:None)
            self.addCleanup(broker.close)
            with patch.dict(os.environ,{'MM_CERTIFICATION_LANE':'pump'}):
                broker.consumers.register('pump:p',['x','x'],'pump_window',101,candidate_id='p')
                broker.consumers.register('pump:p',['x'],'pump_window',110,candidate_id='p')
                broker.consumers.failure('provider_unavailable')
            with patch.dict(os.environ,{'MM_CERTIFICATION_LANE':'meteora'}):
                broker.consumers.register('meteora:q',['y'],'dlmm_fresh',110,candidate_id='q')
            broker.consumers.first_transport(['x'])
            now[0]=102
            p=broker.consumers.telemetry('pump');m=broker.consumers.telemetry('meteora')
            self.assertEqual(p['by_kind']['pump_window']['consumer_deadline_expired'],1)
            self.assertNotIn('pump_window',m['by_kind'])
            self.assertEqual(p['candidate_interests'],1)
            self.assertEqual(m['acquisition_failures'],{})
            self.assertEqual(broker.db.execute("SELECT deadline,created_at,first_transport_at FROM evidence_consumers WHERE owner='pump:p'").fetchone(),(101,100,100))
            self.assertEqual(broker.db.execute('SELECT COUNT(*) FROM evidence_terminals').fetchone()[0],1)
    def test_prefetch_yields_to_admitted_foreground_until_original_deadline(self):
        broker=EvidenceBroker(':memory:',clock=lambda:100,sleeper=lambda _:None)
        self.addCleanup(broker.close)
        broker.consumers.register('background',['b'],'stream_prefetch',110)
        self.assertEqual(len(broker.consumers.batch()),1)
        broker.consumers.register('candidate',['c'],'pump_window',105,candidate_id='c')
        self.assertEqual(broker.consumers.batch(),[])
        broker.consumers.settle('candidate','explicit_terminal')
        self.assertEqual(len(broker.consumers.batch()),1)
