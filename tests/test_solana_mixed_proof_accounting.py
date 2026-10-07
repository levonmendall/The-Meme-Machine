import unittest
from engineering.solana_capacity.live_probe import normal_drain
from engineering.solana_capacity.final_mixed import position_disposition


class RunningDrain(unittest.TestCase):
    def sample(self,t,n,closed=False):
        return dict(at=t,depth=n,closed=closed,completed=t*10)
    def test_shutdown_zero_cannot_prove_live_drain(self):
        samples=[self.sample(t,58) for t in range(20)]+[self.sample(t,0,True) for t in range(20,40)]
        self.assertFalse(normal_drain(samples,0,19,64)['proven'])
    def test_peak_then_completed_running_service_with_stable_tail(self):
        samples=[self.sample(0,58)]+[self.sample(t,max(0,58-t*6)) for t in range(1,30)]
        proof=normal_drain(samples,0,29,64)
        self.assertTrue(proof['proven']);self.assertEqual(proof['peak_to_half_seconds'],5)
    def test_high_queue_cannot_redefine_normal_baseline(self):
        samples=[self.sample(t,58 if t<20 else 40) for t in range(40)]
        self.assertFalse(normal_drain(samples,0,39,64)['proven'])
    def test_no_observation_is_not_zero(self):
        self.assertFalse(normal_drain([],0,30,64)['proven'])
    def test_mark_without_continuation_is_not_complete(self):
        self.assertEqual(position_disposition(dict(ready=True,dependencies=dict(ordered_history_ready=False))),'incomplete')
        self.assertEqual(position_disposition(dict(ready=True,dependencies=dict(ordered_history_ready=True))),'completed')
