import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from tests import pump_acceleration_natural_prospective as runner


class PumpProspectAdmissionTests(unittest.TestCase):
    def test_stream_screen_rejects_non_strategy_demand_before_rpc(self):
        creation={"initial_real_token_reserves":1000,"creator":"creator"}
        rows=[
            dict(mint="M",market_time=970,real_token_reserves=430,
                 virtual_quote_reserves=1000,virtual_token_reserves=1000,
                 slot=1,index=0,wallet="a",amount=10,buy=True),
            dict(mint="M",market_time=985,real_token_reserves=420,
                 virtual_quote_reserves=1010,virtual_token_reserves=990,
                 slot=2,index=0,wallet="a",amount=10,buy=True),
            dict(mint="M",market_time=1000,real_token_reserves=410,
                 virtual_quote_reserves=1020,virtual_token_reserves=980,
                 slot=3,index=0,wallet="a",amount=10,buy=True),
        ]
        confirmations=MagicMock()
        confirmations.signal_inputs.return_value=dict(
            cluster_map={},excluded_clusters=[],skilled_wallet_clusters=0,
            creator_quality_bps=None,creator_history_launches=0,
        )
        signal,_,_=runner._late_stream_signal(creation,rows,rows[-1],confirmations)
        decision=runner.qualify(signal)
        self.assertFalse(decision.qualified)
        self.assertIn("independent_buyers",decision.reasons)

    def test_stream_screen_pass_is_not_trade_authority(self):
        self.assertIn("never grants trade authority",runner._late_stream_signal.__doc__)


if __name__=="__main__":
    unittest.main()
