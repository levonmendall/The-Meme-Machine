"""Production run boundary, with local fixtures and no provider transports."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.meteora.solana_evidence_runtime import RuntimeEvidence
from tests.lanes.meteora import solana_dlmm_independent_v1 as lane

class Run369Admission(unittest.TestCase):
    def test_unavailable_plane_is_persisted_and_never_reaches_economic_screen(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);output=root/'report.json'
            plane=RuntimeEvidence(root/'missing',owner='meteora')
            def candidates(*args):yield dict(address='pool',signal_observed_at=0)
            with patch.object(lane,'EVIDENCE_PLANE',plane),patch.object(lane,'OUT',output), \
                 patch.object(lane,'DLMM_BROKER_DB',root/'broker'), \
                 patch.object(lane,'_prove_network_identity',return_value={'verified':True}), \
                 patch.object(lane,'ProgramAccountWakeStream') as stream, \
                 patch.object(lane,'_campaign_candidates',side_effect=candidates), \
                 patch.object(lane,'_new_adapter',side_effect=AssertionError('economic_screen_forbidden')), \
                 patch('builtins.print'):
                stream.return_value.run.side_effect=lambda stop,ready:ready.set()
                report=lane.run_live(target=1,max_attempted=1,max_runtime_seconds=60)
            plane.close();persisted=json.loads(output.read_text())
            self.assertEqual(report['compatibility_screened_count'],0)
            self.assertEqual(persisted['attempts'][0]['terminal_classification'],'infrastructure_evidence_unavailable')
            self.assertFalse(persisted['attempts'][0]['economic_rejection'])
            self.assertTrue(persisted['accounting']['reconciled'])
            self.assertEqual(persisted['accounting']['unsettled'],0)
