"""Actual Pump loop: exact flat completion versus bounded evidence failure."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.pump import runner as lane
from meme_machine.lanes.pump.solana_evidence_plane import EvidenceUnavailable


class Run369PumpLoop(unittest.TestCase):
    def run_case(self,usable):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);report=root/'native.json';clock=[1000.0]
            health=dict(state='USABLE' if usable else 'WARMING',usable=usable,
                        reason='authoritative_current' if usable else 'evidence_cold_start')
            plane=SimpleNamespace(health=lambda _:health,telemetry=lambda:{},close=lambda:None)
            session=SimpleNamespace(finish=lambda:None,history=[],rpc=SimpleNamespace(provider_telemetry=lambda:{}))
            def tick(seconds):clock[0]+=seconds
            with patch.object(lane,'REPORT',report),patch.object(lane,'RuntimeEvidence',return_value=plane), \
                 patch.object(lane,'Sessions',return_value=session),patch.object(lane,'PumpLogStream') as stream, \
                 patch.object(lane,'LocalPumpTape') as tape, \
                 patch.object(lane,'primary_rpc_url',return_value='https://solana-mainnet.g.alchemy.com/v2/offline-fixture'), \
                 patch.object(lane.time,'time',side_effect=lambda:clock[0]), \
                 patch.object(lane.time,'monotonic',side_effect=lambda:clock[0]), \
                 patch.object(lane.time,'sleep',side_effect=tick), \
                 patch.dict(lane.os.environ,{'MM_OPERATIONAL_PHASE':'smoke','MM_SOLANA_EVIDENCE_BROKER_DB':str(root/'broker')}), \
                 patch('builtins.print'):
                stream.return_value.run.side_effect=lambda stop,ready:ready.set()
                tape.return_value.status.return_value={}
                tape.return_value.events_since.return_value=([],0)
                if not usable:tape.return_value.events_since.side_effect=EvidenceUnavailable('evidence_cold_start')
                if usable:lane.main(campaign=True,discovery_seconds=600)
                else:
                    with self.assertRaisesRegex(lane.Unavailable,'evidence_cold_start'):
                        lane.main(campaign=True,discovery_seconds=600)
            return json.loads(report.read_text()),clock[0]-1000

    def test_actual_loop_clean_flat_completion(self):
        report,elapsed=self.run_case(True)
        self.assertEqual(report['smoke_tail_exit'],'flat_after_discovery')
        self.assertEqual(elapsed,600)
        self.assertEqual(report['pending_entries'],[]);self.assertEqual(report['open_positions'],[])
        self.assertGreater(report['evidence_liveness']['usable_observations'],0)

    def test_actual_loop_classifies_stalled_plane_before_entire_smoke(self):
        report,elapsed=self.run_case(False)
        self.assertEqual(report['infrastructure_failure'],'evidence_cold_start')
        self.assertEqual(elapsed,90)
        self.assertNotIn('smoke_tail_exit',report)
        self.assertEqual(report['pending_entries'],[]);self.assertEqual(report['open_positions'],[])
