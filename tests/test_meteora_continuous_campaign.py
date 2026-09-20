"""Continuous orchestration checks with a deterministic clock and no provider I/O."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine import dlmm
from tests import solana_dlmm_independent_v1 as strategy


class ContinuousCampaignTests(unittest.TestCase):
    def test_attempt_budget_rolls_without_raising_original_window_capacity(self):
        budget=strategy.CampaignAttemptBudget(2)
        self.assertTrue(budget.take(0));self.assertTrue(budget.take(1))
        self.assertFalse(budget.take(1199))
        self.assertTrue(budget.take(1200));self.assertFalse(budget.take(1200.5))
        self.assertTrue(budget.take(1201))

    def test_repeated_census_only_admits_new_first_sightings(self):
        clock=[0];telemetry={};phases=[];history=[]
        def row(name):return dict(address=name,name=name,tvl=1000,is_blacklisted=False,
            token_x=dict(address=dlmm.WSOL),token_y=dict(address='token'),volume={'30m':1000},fees={'30m':10})
        def api(*args,**kw):return dict(data=[row('first')]+([row('new')] if clock[0]>=60 else []))
        def acceleration(candidate,at):
            history.append((candidate['address'],at))
            return dict(candidate,volume_acceleration=0 if clock[0]==0 else 3,fee_acceleration=3)
        with patch.object(strategy.time,'monotonic',side_effect=lambda:clock[0]),patch.object(strategy.time,'time',side_effect=lambda:2800+clock[0]),patch.object(strategy.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)),patch.object(strategy,'_api',side_effect=api),patch.object(strategy,'_history_acceleration',side_effect=acceleration):
            candidates=list(strategy._campaign_candidates(strategy.load_policy(),telemetry,121,phases.append))
        self.assertEqual(history,[('first',2800),('new',2860)])
        self.assertEqual([x['address'] for x in candidates],['new'])
        self.assertEqual(telemetry['seen'],2);self.assertEqual(telemetry['census_cycles'],3)
        self.assertEqual(clock[0],121)

    def test_four_hours_requires_explicit_campaign_and_policy_does_not_change(self):
        before=strategy.digest(strategy.load_policy())
        with self.assertRaisesRegex(ValueError,'runtime_bound'):strategy.run_live(max_runtime_seconds=14400)
        with tempfile.TemporaryDirectory() as td,patch.object(strategy,'OUT',Path(td)/'report.json'),patch.object(strategy,'_prove_network_identity',side_effect=RuntimeError('offline-network-boundary')):
            with self.assertRaisesRegex(RuntimeError,'offline-network-boundary'):
                strategy.run_live(max_runtime_seconds=14400,campaign=True)
        self.assertEqual(before,strategy.digest(strategy.load_policy()))
