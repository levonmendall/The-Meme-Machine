import unittest
from unittest.mock import patch

from meme_machine import dlmm
from tests import dlmm_capital_efficiency_v1 as strategy


class CapitalEfficiencyV1Tests(unittest.TestCase):
    def test_frozen_rule_has_no_absolute_tvl_floor(self):
        rule=strategy.load_rule()
        self.assertIsNone(rule["discovery"]["minimum_pool_tvl_usd"])
        self.assertIsNone(rule["discovery"]["minimum_absolute_volume"])
        self.assertEqual(rule["position"]["width_bins"],70)
        self.assertEqual(rule["position"]["distribution"],"sdk_bidask_one_side_sol")
        self.assertEqual(rule["management"]["maximum_hold_seconds"],180)
        self.assertEqual(rule["revision"],"1.1")

    def test_qualification_requires_all_economic_and_risk_checks(self):
        rule=strategy.load_rule()
        base=dict(
            range_liquidity_to_capital_multiple=10.0,
            projected_range_fee_capture_lamports=700000.0,
            flow_into_range_volume_sol_lamports=1,
            two_way_balance=0.50,
            reversal_count=1,
            touch_then_revert=False,
            near_range_drift_ratio=0.50,
            stress_unwind=dict(unwind_loss_bps=70.0),
        )
        decision=strategy.qualify(base,rule)
        self.assertTrue(decision["passes"])
        for key,mutation in (
            ("capacity",dict(range_liquidity_to_capital_multiple=9.99)),
            ("fee",dict(projected_range_fee_capture_lamports=699999)),
            ("flow",dict(flow_into_range_volume_sol_lamports=0)),
            ("two_way",dict(two_way_balance=0.49)),
            ("reversal",dict(reversal_count=0,touch_then_revert=False)),
            ("drift",dict(near_range_drift_ratio=0.5001)),
        ):
            row=dict(base);row.update(mutation)
            d=strategy.qualify(row,rule)
            self.assertFalse(d["passes"],key)
            self.assertIn(key,d["failed"])
        row=dict(base);row["stress_unwind"]=dict(unwind_loss_bps=70.01)
        d=strategy.qualify(row,rule)
        self.assertFalse(d["passes"]);self.assertIn("unwind",d["failed"])

    def test_70_bin_range_is_one_sided_relative_to_active(self):
        bins={str(i):{} for i in range(-100,101)}
        sol_y=dict(active=0,x="token",y=dlmm.WSOL,bins=bins)
        self.assertEqual(strategy._range_ids(sol_y,70),list(range(-70,0)))
        sol_x=dict(active=0,x=dlmm.WSOL,y="token",bins=bins)
        self.assertEqual(strategy._range_ids(sol_x,70),list(range(1,71)))

    def test_discovery_unions_volume_and_fee_density_without_tvl_filter(self):
        def pool(address,tvl,vol,fee_ratio):
            return dict(
                address=address,name=address,tvl=tvl,is_blacklisted=False,
                token_x=dict(address=dlmm.WSOL),
                token_y=dict(address="token-"+address),
                volume={"30m":vol},fees={"30m":1},
                fee_tvl_ratio={"30m":fee_ratio},dynamic_fee_pct=0.1,
            )
        volume=[pool("volume-small",5000,100000,0.01)]
        density=[pool("density-tiny",500,1000,5.0)]
        calls=[]
        def fake(path,params=None,allow_pnl=False):
            calls.append(params)
            rows=volume if params["sort_by"]=="volume_30m:desc" else density
            return {"data":rows}
        with patch.object(strategy.api,"_json_get",side_effect=fake):
            rows=strategy.discover(10)
        self.assertEqual({r["address"] for r in rows},
                         {"volume-small","density-tiny"})
        self.assertTrue(all("tvl" not in x["filter_by"] for x in calls))

    def test_far_edge_escape_is_orientation_correct(self):
        position=dict(lower=-70,upper=-1)
        self.assertFalse(strategy._far_edge_escaped(
            position,dict(active=0,y=dlmm.WSOL,x="token")))
        self.assertTrue(strategy._far_edge_escaped(
            position,dict(active=-71,y=dlmm.WSOL,x="token")))
        position=dict(lower=1,upper=70)
        self.assertFalse(strategy._far_edge_escaped(
            position,dict(active=0,x=dlmm.WSOL,y="token")))
        self.assertTrue(strategy._far_edge_escaped(
            position,dict(active=71,x=dlmm.WSOL,y="token")))


if __name__=="__main__":
    unittest.main()
