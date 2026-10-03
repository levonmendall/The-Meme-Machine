"""Live ingress must wire the existing negative-only PumpSwap prospect screen."""
import unittest
from unittest.mock import patch
from meme_machine.lanes.pump.solana_evidence_broker import EvidenceBroker
from meme_machine.lanes.pump.pump_acceleration_history import IncrementalPumpSwapHistory
from meme_machine.lanes.pump.pump_acceleration_evidence import PUMPSWAP_PROGRAM
from tests.lanes.pump.test_stream_payload_retention import ingest


class RecordingRPC:
    def __init__(self):self.signatures=[]
    def call_many(self,method,params,*args,**kwargs):
        self.signatures.extend(p[0] for p in params)
        return [None for _ in params]


class StreamNegativeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.b=EvidenceBroker(':memory:',clock=lambda:1000,sleeper=lambda n:None)
        self.addCleanup(self.b.close)

    def history(self,key):
        return IncrementalPumpSwapHistory('pool',900,broker=self.b,stream_key=key)

    def test_thousand_proven_unrelated_notifications_remain_observed_without_rpc_consumers(self):
        values=[dict(signature='noise-'+str(i),err=None,
            logs=['Program Other111 invoke [1]','Program Other111 success']) for i in range(1000)]
        key,_=ingest(self.b,values);history=self.history(key);rpc=RecordingRPC()
        with patch('meme_machine.lanes.pump.pump_acceleration_history.time.time',return_value=1000):
            history._ingest_stream_window(rpc,1000)
        self.assertEqual(rpc.signatures,[])
        self.assertEqual(len(history.stream_prefiltered_signatures),1000)
        self.assertEqual(history.status(1000)['stream_prefiltered_signatures'],1000)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM stream_signature_archive').fetchone()[0],1000)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM evidence_consumers').fetchone()[0],0)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.assertEqual(history.stream_pending_transactions,0)
        self.assertEqual(history.events,{})

    def test_only_missing_empty_truncated_or_pool_trade_logs_require_body(self):
        values=[dict(signature='missing',err=None),dict(signature='empty',err=None,logs=[]),
            dict(signature='truncated',err=None,logs=['Program Other111 invoke [1]','Log truncated']),
            dict(signature='possible',err=None,logs=['Program '+PUMPSWAP_PROGRAM+' invoke [1]'])]
        key,_=ingest(self.b,values);history=self.history(key);rpc=RecordingRPC()
        with patch('meme_machine.lanes.pump.pump_acceleration_history.time.time',return_value=1000):
            history._ingest_stream_window(rpc,1000)
        self.assertEqual(set(rpc.signatures),{'missing','empty','truncated'})
        self.assertEqual(history.stream_pending_transactions,3)
        self.assertEqual(history.events,{})
        self.assertEqual(len(history.stream_prefiltered_signatures),1)

    def test_later_possible_trade_for_same_pool_is_not_suppressed_by_prior_negative(self):
        key,_=ingest(self.b,[dict(signature='noise',err=None,logs=['Program Other111 success'])])
        history=self.history(key);rpc=RecordingRPC()
        with patch('meme_machine.lanes.pump.pump_acceleration_history.time.time',return_value=1000):
            history._ingest_stream_window(rpc,1000)
            ingest(self.b,[dict(signature='later',err=None,logs=['Program '+PUMPSWAP_PROGRAM+' invoke [1]','Log truncated'])])
            history._ingest_stream_window(rpc,1000)
        self.assertEqual(rpc.signatures,['later'])
        self.assertEqual(history.stream_pending_transactions,1)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM stream_signature_archive').fetchone()[0],2)
