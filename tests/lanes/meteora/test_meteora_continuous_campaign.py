"""Continuous orchestration checks with a deterministic clock and no provider I/O."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.meteora import dlmm
from meme_machine.lanes.meteora import runner as strategy


class ContinuousCampaignTests(unittest.TestCase):
    def test_attempt_budget_rolls_without_raising_original_window_capacity(self):
        budget=strategy.CampaignAttemptBudget(2)
        self.assertTrue(budget.take(0));self.assertTrue(budget.take(1))
        self.assertFalse(budget.take(1199))
        self.assertTrue(budget.take(1200));self.assertFalse(budget.take(1200.5))
        self.assertTrue(budget.take(1201))

    def test_attempt_budget_pressure_never_rejects_candidate_evaluation(self):
        budget=strategy.CampaignAttemptBudget(1)
        first=strategy._attempt_budget_state(budget,0,True)
        pressured=strategy._attempt_budget_state(budget,1,True)
        self.assertEqual(first,dict(pressure=False,evaluate=True))
        self.assertEqual(pressured,dict(pressure=True,evaluate=True))

    def test_campaign_handoff_uses_snapshot_context_and_closes_source(self):
        import time
        telemetry={};phases=[]
        def row(name):return dict(address=name,name=name,tvl=1000,is_blacklisted=False,
            token_x=dict(address=dlmm.WSOL),token_y=dict(address='token'),
            volume={'5m':100,'30m':1000},fees={'5m':1,'30m':10})
        with tempfile.TemporaryDirectory() as td,patch.object(strategy,'OUT',Path(td)/'report.json'), \
             patch.object(strategy,'_api',return_value=dict(data=[row('first')])), \
             patch.object(strategy,'_history_acceleration') as history:
            stream=strategy._campaign_candidates(strategy.load_policy(),telemetry,time.monotonic()+5,phases.append)
            candidate=next(stream);stream.close()
        history.assert_not_called()
        self.assertEqual(candidate['address'],'first')
        self.assertEqual(telemetry['history_reads'],0)
        self.assertEqual(telemetry['seen'],1)
        self.assertFalse(telemetry['source_acquisition']['producer_running'])
        self.assertTrue(telemetry['source_acquisition']['producer_done'])

    def test_multi_hour_profitability_runtime_preserves_policy_and_campaign_is_operational_only(self):
        before=strategy.digest(strategy.load_policy())
        with self.assertRaisesRegex(ValueError,'runtime_bound'):
            strategy.run_live(max_runtime_seconds=90001)
        for campaign in (False,True):
            with tempfile.TemporaryDirectory() as td,patch.object(strategy,'OUT',Path(td)/'report.json'),patch.object(strategy,'_prove_network_identity',side_effect=RuntimeError('offline-network-boundary')):
                with self.assertRaisesRegex(RuntimeError,'offline-network-boundary'):
                    strategy.run_live(max_runtime_seconds=14400,campaign=campaign)
        self.assertEqual(before,strategy.digest(strategy.load_policy()))
