"""Production Meteora capture/trigger gates using synthetic finalized wire data."""
import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.meteora import dlmm
from meme_machine.lanes.meteora.solana_evidence_plane import EvidenceWriter,EvidenceUnavailable
from meme_machine.lanes.meteora.solana_evidence_service import FinalizedFence
from meme_machine.lanes.meteora.solana_evidence_transport import Subscription
from meme_machine.lanes.meteora.solana_evidence_runtime import RuntimeEvidence,METEORA_SCOPE
from meme_machine.lanes.meteora.dlmm_tape import reconstruct
from meme_machine.lanes.meteora import runner as lane
from tests.test_meteora_tape import interval,encode_state

class ProductionCutover(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.writer=EvidenceWriter(Path(self.temp.name)/'db',clock=lambda:113)
        self.fence=FinalizedFence(self.writer,endpoint_identity='a'*64)
        self.raw,self.start,self.end,self.signatures,self.transactions=interval()
        post=dlmm.validate(self.end,102);self.end=encode_state(self.raw,post,112,112)
        sub=Subscription('service',METEORA_SCOPE,dlmm.PROGRAM,'transactions',4)
        for slot in range(99,114):
            tx=(self.transactions['synthetic-signature'] if slot==101 else dict(transaction=dict(signatures=['anchor'+str(slot)],message=dict(accountKeys=[self.start['pool'],dlmm.PROGRAM],instructions=[])),meta=dict(err={'synthetic':True},logMessages=[])))
            self.fence.block(sub,dict(method='blockNotification',params=dict(result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,blockTime=slot,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),transactions=[tx]))))),113)
        self.fence.health('phase','ACTIVE');self.fence.health('heartbeat',113)
        self.plane=RuntimeEvidence(self.writer.path,owner='meteora',clock=lambda:113,command=self.fence.command)
        self.network=patch('socket.socket.connect',side_effect=AssertionError('network_forbidden'));self.network.start()
        self.plane_patch=patch.object(lane,'EVIDENCE_PLANE',self.plane);self.plane_patch.start()
    def tearDown(self):self.plane_patch.stop();self.network.stop();self.plane.close();self.writer.close();self.temp.cleanup()
    def test_actual_trigger_and_twelve_second_capture_zero_history(self):
        adapter=SimpleNamespace(snapshot_from_state=lambda *a,**k:self.end)
        triggers,meta=lane._new_finalized_swaps(None,self.start['pool'],100)
        self.assertEqual([r['signature'] for r in triggers],['synthetic-signature'])
        with patch.object(lane.time,'sleep') as sleep,patch.object(lane.time,'time',return_value=113):
            tape,cursor,census=lane._capture_chunk(adapter,self.start,[100,2**31-1,2**31-1],12)
        sleep.assert_called_once_with(12)
        direct=reconstruct(self.start,self.end,self.signatures,self.transactions,113,[100,2**31-1,2**31-1])
        self.assertEqual(tape.terminal,direct.terminal)
        clean=lambda e:{k:v for k,v in e.items() if k not in ('cursor','transaction_index')}
        self.assertEqual([clean(e) for e in tape.events],[clean(e) for e in direct.events])
        self.assertEqual(meta['historical_provider_calls'],0);self.assertEqual(census['historical_provider_calls'],0)
    def test_missing_delivery_blocks_real_capture_and_trigger(self):
        self.writer.gap(METEORA_SCOPE,101,101)
        with self.assertRaises(EvidenceUnavailable):lane._new_finalized_swaps(None,self.start['pool'],100)
        with patch.object(lane.time,'sleep'),patch.object(lane.time,'time',return_value=113):
            with self.assertRaises(EvidenceUnavailable):lane._capture_chunk(SimpleNamespace(snapshot_from_state=lambda *a,**k:self.end),self.start,[100,0,0],12)
