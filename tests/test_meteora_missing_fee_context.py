import unittest
from unittest.mock import patch
from meme_machine.lanes.meteora import dlmm
from meme_machine.lanes.meteora import runner as runner


class MissingFeeContextTests(unittest.TestCase):
    def row(self):
        # Captured list-response shape: five-minute keys are absent, not zero.
        return dict(address='pool',token_x=dict(address=dlmm.WSOL),
                    token_y=dict(address='token'),tvl=1000,
                    volume={'30m':1000},fees={'30m':30})

    def test_missing_five_minute_context_uses_existing_completed_bucket_reader(self):
        calls=[]
        def api(path,params=None):
            calls.append(path)
            if path=='/pools':return dict(data=[self.row()])
            return dict(data=[dict(timestamp=i*300,volume=100,fees=5) for i in range(1,8)])
        telemetry={}
        with patch.object(runner,'_api',side_effect=api),patch.object(runner.time,'time',return_value=2200):
            rows=list(runner._iter_acceleration_candidates({'regime':{}},telemetry))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['fee_5m_usd'],5)
        self.assertEqual(rows[0]['acceleration_window_end_exclusive'],2100)
        self.assertEqual(telemetry['history_reads'],1)
        self.assertEqual(telemetry['rejections'],[])
        self.assertEqual(calls.count('/pools/pool/volume/history'),1)

    def test_failed_missing_context_is_incomplete_evidence_never_zero_fee_rejection(self):
        def api(path,params=None):
            if path=='/pools':return dict(data=[self.row()])
            return dict(data=[])
        telemetry={}
        with patch.object(runner,'_api',side_effect=api):
            self.assertEqual(list(runner._iter_acceleration_candidates({'regime':{}},telemetry)),[])
        self.assertEqual(telemetry['rejections'],[])
        self.assertEqual(telemetry['errors'][0]['failure_domain'],'incomplete_evidence')
        self.assertFalse(telemetry['errors'][0]['qualification_inferred'])

    def test_measured_zero_is_still_rejected_without_an_extra_history_request(self):
        row=self.row();row['fees']['5m']=0;row['volume']['5m']=0
        telemetry={}
        with patch.object(runner,'_api',return_value=dict(data=[row])),patch.object(runner,'_history_acceleration') as history:
            self.assertEqual(list(runner._iter_acceleration_candidates({'regime':{}},telemetry)),[])
        history.assert_not_called()
        self.assertEqual(telemetry['rejections'][0]['failed'],['public_fee_context_zero'])
