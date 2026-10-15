import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from meme_machine.lanes.pump import runner as runner


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
        decision,reasons=runner._late_stream_prospect(signal)
        self.assertTrue(reasons)
        self.assertIn("independent_buyers",reasons)
        self.assertFalse(decision.qualified)

    def test_same_mint_reenters_when_finalized_demand_improves(self):
        creation={"initial_real_token_reserves":1000,"creator":"creator"}
        confirmations=MagicMock()
        confirmations.signal_inputs.return_value=dict(cluster_map={},excluded_clusters=[],
            skilled_wallet_clusters=0,creator_quality_bps=None,creator_history_launches=0)
        def event(t,reserve,wallet,index):
            return dict(mint='M',market_time=t,real_token_reserves=reserve,
                virtual_quote_reserves=1000,virtual_token_reserves=1000,
                slot=index,index=0,wallet=wallet,amount=10,buy=True)
        weak=[event(970,430,'a',1),event(985,420,'a',2),event(1000,410,'a',3)]
        signal,_,_=runner._late_stream_signal(creation,weak,weak[-1],confirmations)
        _decision,reasons=runner._late_stream_prospect(signal)
        self.assertTrue(reasons)
        # Profitability-v1 requires broad expanding independent demand. Keep
        # the test focused on reconsideration: first observation rejects, a later
        # genuinely improved finalized state is allowed through to RPC evaluation.
        improved=[]
        for i in range(12):
            improved.append(event(1005+i,400-5*i,f"r{i}",10+i))
        for i in range(20):
            improved.append(event(1020+min(i,10),300-9*i,f"r{i}",30+i))
        improved[-1]=event(1030,200,"r19",49)
        signal,_,_=runner._late_stream_signal(creation,improved,improved[-1],confirmations)
        decision,reasons=runner._late_stream_prospect(signal)
        self.assertFalse(reasons,reasons)
        self.assertFalse(decision.qualified)
        self.assertIn("executable_downside_unavailable",decision.reasons)
        self.assertEqual(signal.concentration_bps,0)  # optimistic only; RPC still required


if __name__=="__main__":
    unittest.main()
