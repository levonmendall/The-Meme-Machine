"""Offline smoke of the combined Pump #126 / Pons #127 PAPER launch wiring.

No provider, funded positions, network transport, or real portfolio state.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.operational.supervisor import Supervisor,pons_held_shadow_settings
from meme_machine.lanes.pons.held_paper_shadow import PaperHeldShadow
from meme_machine.lanes.pump.postgrad import held_rpc_mode


class LivePaperOptimizationIntegration(unittest.TestCase):
    def supervisor(self,folder):
        instance=object.__new__(Supervisor)
        instance.root=Path(folder)
        instance.epoch='offline-fixture-pump-pons-flags'
        instance.offline=True
        return instance

    def test_both_opt_ins_reach_only_the_correct_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor=self.supervisor(folder)
            settings={
                'MM_PUMP_HELD_RPC_MODE':'optimized',
                'MM_PONS_HELD_PAPER_SHADOW':'1',
                'MM_PONS_HELD_SHADOW_MAX_SAMPLES':'8',
                'MM_PONS_HELD_SHADOW_EVERY_TICKS':'10',
            }
            with patch.dict(os.environ,settings):
                pump=supervisor.environment('pump')
                pons=supervisor.environment('pons')
                self.assertEqual(pump['MM_PUMP_HELD_RPC_MODE'],'optimized')
                self.assertNotIn('MM_PONS_HELD_PAPER_SHADOW',pump)
                self.assertEqual(pons['MM_PONS_HELD_PAPER_SHADOW'],'1')
                self.assertEqual(pons['MM_PONS_HELD_SHADOW_MAX_SAMPLES'],'8')
                self.assertEqual(pons['MM_PONS_HELD_SHADOW_EVERY_TICKS'],'10')
                self.assertNotIn('MM_PUMP_HELD_RPC_MODE',pons)
                self.assertEqual(held_rpc_mode(pump),'optimized')
                shadow=PaperHeldShadow('https://offline.invalid',environ=pons)
                self.assertTrue(shadow.enabled)
                self.assertFalse(shadow.status()['quote_suppression_enabled'])
                self.assertFalse(shadow.status()['can_skip_quotes'])

    def test_default_off_and_original_pump_reads_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor=self.supervisor(folder)
            with patch.dict(os.environ,{
                'MM_PUMP_HELD_RPC_MODE':'baseline',
                'MM_PONS_HELD_PAPER_SHADOW':'0',
            }):
                pump=supervisor.environment('pump')
                pons=supervisor.environment('pons')
                self.assertEqual(held_rpc_mode(pump),'baseline')
                self.assertEqual(pons['MM_PONS_HELD_PAPER_SHADOW'],'0')
                self.assertFalse(PaperHeldShadow('https://offline.invalid',
                                                environ=pons).enabled)

    def test_invalid_shadow_bounds_fail_closed_before_worker_launch(self):
        for settings in (
            {'MM_PONS_HELD_PAPER_SHADOW':'bad'},
            {'MM_PONS_HELD_PAPER_SHADOW':'1',
             'MM_PONS_HELD_SHADOW_MAX_SAMPLES':'33'},
            {'MM_PONS_HELD_PAPER_SHADOW':'1',
             'MM_PONS_HELD_SHADOW_EVERY_TICKS':'0'},
            {'MM_PONS_HELD_PAPER_SHADOW':'1',
             'MM_PONS_HELD_SHADOW_MAX_SAMPLES':'abc'},
        ):
            with self.subTest(settings=settings),self.assertRaises(ValueError):
                pons_held_shadow_settings(settings)


if __name__=='__main__':
    unittest.main()
