import unittest
from unittest.mock import patch
from meme_machine.lanes.meteora import dlmm
from tests.lanes.meteora import solana_dlmm_independent_v1 as runner

class MeteoraMarketScopeEfficiencyTests(unittest.TestCase):
    def test_discovery_uses_pool_snapshot_without_per_pool_history_request(self):
        calls=[]
        row={"address":"pool","token_x":{"address":dlmm.WSOL},
             "token_y":{"address":"token"},"tvl":1000,
             "volume":{"5m":100,"30m":300},"fees":{"5m":10,"30m":30}}
        def api(path,params=None):
            calls.append(path)
            if path=="/pools":return {"data":[row]}
            raise AssertionError(path)
        telemetry={}
        with patch.object(runner,"_api",side_effect=api):
            item=next(runner._iter_acceleration_candidates({"regime":{}},telemetry))
        self.assertEqual(item["public_context_source"],"pool_list_snapshot")
        self.assertEqual(telemetry["history_reads"],0)
        self.assertFalse(any("volume/history" in path for path in calls))

    def test_public_context_is_derived_without_an_extra_request(self):
        item=runner._candidate({"address":"pool","token_x":{"address":dlmm.WSOL},
            "token_y":{"address":"token"},"tvl":1000,
            "volume":{"5m":1,"30m":1000},"fees":{"5m":1,"30m":1000}})
        self.assertIn("volume_acceleration",item)
        self.assertEqual(item["public_context_source"],"pool_list_snapshot")

if __name__ == "__main__":
    unittest.main()

class PostRunCapitalClassificationTests(unittest.TestCase):
    def test_capital_occupancy_and_open_handoff_are_not_reconstruction_failures(self):
        from meme_machine.lanes.meteora.runner import _record_progress
        from meme_machine.lanes.meteora.pipeline import Pipeline
        p=Pipeline(':memory:','meteora','policy')
        try:
            _record_progress(p,{},'occupied','terminal','paper_capital_occupied')
            _record_progress(p,{},'open','terminal','durable_position_continuation_active')
            summary=p.snapshot()['unique_classes']
            self.assertEqual(summary['capital_occupied'],1)
            self.assertEqual(summary['open_continuing'],1)
            self.assertEqual(summary['reconstruction_incomplete'],0)
            _record_progress(p,{},'missing','terminal','fresh_state_unavailable_after_authenticated_trigger')
            self.assertEqual(p.snapshot()['unique_classes']['reconstruction_incomplete'],1)
        finally:p.close()
