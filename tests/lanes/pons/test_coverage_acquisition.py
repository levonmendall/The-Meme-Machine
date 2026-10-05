"""Regressions for first-hour acquisition losses; no market requests."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons import pons_selective_acquisition as acquisition
from meme_machine.lanes.pons.provider import Rpc
from tests.lanes.pons.test_pons_selective_continuation import state, snapshots, events

class CachedLaunchAgeTests(unittest.TestCase):
    def evaluate(self, ctx, asof=200):
        candidate=dict(token='token',curve='curve',block=1,
            stamp=SimpleNamespace(event_at=asof), header={'timestamp':hex(asof)},
            state=state(timestamp=asof), record={'graduationThreshold':10**18,'pairToken':'0x'+'00'*20},
            current_snipe_bps=0, roundtrip_gas_wei=10**10,
            decoded_event={'decoded':{'name':'CurveBuy'}})
        event=dict(blockNumber='0x1',blockHash='hash',transactionHash='tx',logIndex='0x0')
        with patch.object(acquisition,'_authenticate_candidate',return_value=candidate):
            return acquisition.evaluate_candidate('unused',event,[],strategy_capital_quote=10**18,
                evidence_context=ctx)

    def context(self, launch):
        ctx=MagicMock();ctx.telemetry.return_value={}
        ctx.cache=acquisition.ImmutableEvidenceCache()
        if launch is not None:ctx.cache.remember_launch('curve',launch)
        return ctx

    def test_repeated_out_of_age_candidates_do_not_block_trajectory(self):
        for launch in (111,0):
            ctx=self.context(launch)
            asof=200 if launch else 901
            with patch.object(acquisition,'_trajectory') as trajectory, patch.object(
                    acquisition,'_authenticate_window') as window:
                for _ in range(3):
                    row=self.evaluate(ctx,asof)
                    self.assertEqual(row['vector']['all_rejections'],['token_age'])
                    self.assertFalse(row['vector']['complete'])
                    self.assertFalse(row['vector']['trajectory']['acquired'])
                    self.assertTrue(row['timing']['cached_launch_age_screen_only'])
                trajectory.assert_not_called();window.assert_not_called()

    def test_boundary_and_cold_candidates_still_reach_full_qualification(self):
        for launch in (110,0,None):
            asof=900 if launch==0 else 200
            ctx=self.context(launch)
            snap=[dict(r,at=r['at']+asof-200) for r in snapshots()]
            market=[dict(r,event_at=r['event_at']+asof-200) for r in events()]
            with patch.object(acquisition,'_trajectory',return_value=(snap,50 if launch is None else launch,{})) as trajectory, \
                 patch.object(acquisition,'_authenticate_window',return_value=(market,[])) as window, \
                 patch.object(acquisition.time,'time',return_value=asof+2), \
                 patch.object(acquisition,'qualification_vector',wraps=acquisition.qualification_vector) as qualify:
                row=self.evaluate(ctx,asof)
                self.assertTrue(row['vector']['complete'])
                self.assertTrue(row['vector']['current_threshold_pass'],row['vector']['all_rejections'])
                trajectory.assert_called_once();window.assert_called_once();qualify.assert_called_once()

    def test_young_candidate_is_reevaluated_when_original_age_gate_opens(self):
        ctx=self.context(111)
        with patch.object(acquisition,'_trajectory',side_effect=RuntimeError('trajectory_reached')) as trajectory:
            self.assertTrue(self.evaluate(ctx,200)['screened_out'])
            with self.assertRaisesRegex(RuntimeError,'trajectory_reached'):self.evaluate(ctx,201)
            trajectory.assert_called_once()

    def test_invalid_cached_launch_fails_closed(self):
        with self.assertRaisesRegex(BoundaryError,'invalid_curve_launch_time'):
            self.evaluate(self.context(201))

class TransportDeadlineTests(unittest.TestCase):
    class Response:
        def __init__(self, body):self.body=body
        def __enter__(self):return self
        def __exit__(self,*_):return False
        def read(self,*_):return json.dumps(self.body).encode()

    def call(self,rpc,batch):
        return rpc._http_batch([('eth_chainId',[])]) if batch else rpc._http('eth_chainId',[])

    def test_remaining_original_deadline_caps_single_and_batch(self):
        for batch in (False,True):
            rpc=Rpc('https://example.invalid');rpc.evidence_deadline=105
            row={'id':1,'result':'0x1'}
            with patch('meme_machine.lanes.pons.provider.time.monotonic',return_value=103), \
                 patch('meme_machine.lanes.pons.provider.urlopen',return_value=self.Response([row] if batch else row)) as open_:
                self.call(rpc,batch)
                self.assertEqual(open_.call_args.kwargs['timeout'],2)
                self.assertEqual(rpc.timeout,10);self.assertEqual(rpc.evidence_deadline,105)

    def test_expired_deadline_never_transmits(self):
        for batch in (False,True):
            rpc=Rpc('https://example.invalid');rpc.evidence_deadline=105
            with patch('meme_machine.lanes.pons.provider.time.monotonic',return_value=105), \
                 patch('meme_machine.lanes.pons.provider.urlopen') as open_:
                with self.assertRaisesRegex(BoundaryError,'evidence_deadline_before_transport'):self.call(rpc,batch)
                open_.assert_not_called()

    def test_late_success_and_timeout_remain_explicit_consumer_deadlines(self):
        for batch in (False,True):
            for timeout in (False,True):
                rpc=Rpc('https://example.invalid');rpc.evidence_deadline=105
                row={'id':1,'result':'0x1'}
                with patch('meme_machine.lanes.pons.provider.time.monotonic',side_effect=[104,105]), \
                     patch('meme_machine.lanes.pons.provider.urlopen',side_effect=TimeoutError() if timeout else None,
                           return_value=self.Response([row] if batch else row)):
                    with self.assertRaisesRegex(BoundaryError,'evidence_deadline_during_transport'):self.call(rpc,batch)
                self.assertFalse(rpc.cache)

if __name__=='__main__':unittest.main()
