import unittest
from unittest.mock import patch

from meme_machine import dlmm
from tests import dlmm_small_pool_market_opportunity as study


class SmallPoolMarketOpportunityTests(unittest.TestCase):
    def test_exact_sol_pair_requires_one_wsol_leg(self):
        self.assertTrue(study._exact_sol_pair(dict(
            token_x={"address":dlmm.WSOL},token_y={"address":"x"})))
        self.assertTrue(study._exact_sol_pair(dict(
            token_x={"address":"x"},token_y={"address":dlmm.WSOL})))
        self.assertFalse(study._exact_sol_pair(dict(
            token_x={"address":"x"},token_y={"address":"y"})))
        self.assertFalse(study._exact_sol_pair(dict(
            token_x={"address":dlmm.WSOL},token_y={"address":dlmm.WSOL})))

    def test_tvl_filters_are_disjoint(self):
        self.assertEqual(study._filter("<10k"),
                         "is_blacklisted=false && tvl<10000")
        self.assertIn("tvl>=10000",study._filter("10-25k"))
        self.assertIn("tvl<25000",study._filter("10-25k"))
        self.assertIn("tvl>=25000",study._filter("25-50k"))
        self.assertIn("tvl<50000",study._filter("25-50k"))
        self.assertEqual(study._filter(">=50k"),
                         "is_blacklisted=false && tvl>=50000")

    def test_census_fails_open_only_to_exact_sol_rows_and_reports_completion(self):
        rows=[
            dict(address="a",tvl=5000,created_at=1,is_blacklisted=False,
                 volume={"24h":1000},fees={"24h":10},dynamic_fee_pct=0.1,
                 token_x={"address":dlmm.WSOL,"symbol":"SOL"},
                 token_y={"address":"x","symbol":"X"}),
            dict(address="b",tvl=5000,created_at=1,is_blacklisted=False,
                 volume={"24h":1000},fees={"24h":10},dynamic_fee_pct=0.1,
                 token_x={"address":"y","symbol":"Y"},
                 token_y={"address":"z","symbol":"Z"}),
        ]
        with patch.object(study,"_get",return_value=dict(
            data=rows,total=2,pages=1,current_page=1,page_size=1000)):
            out,status=study.census_bucket("<10k")
        self.assertTrue(status["complete"])
        self.assertEqual([x["address"] for x in out],["a"])

    def test_summary_exposes_fee_and_volume_density(self):
        rows=[
            dict(address="a",tvl_usd=1000,volume_24h_usd=2000,
                 fees_24h_usd=20,dynamic_fee_pct=0.1,created_at=900,
                 name="a",token_x="SOL",token_y="A"),
            dict(address="b",tvl_usd=2000,volume_24h_usd=1000,
                 fees_24h_usd=10,dynamic_fee_pct=0.2,created_at=0,
                 name="b",token_x="SOL",token_y="B"),
        ]
        out=study.summarize_bucket(rows,observed_at=1000)
        self.assertEqual(out["pool_count"],2)
        self.assertAlmostEqual(out["median_volume_to_tvl_24h"],1.25)
        self.assertAlmostEqual(out["median_fee_to_tvl_24h"],0.0125)
        self.assertAlmostEqual(
            out["profitable_capacity_proxy_fees_per_1000_tvl_24h"],10.0)
        self.assertEqual(out["share_age_lt_1h"],1.0)

    def test_volatility_sample_is_deterministic_and_not_fee_sorted(self):
        rows=[
            dict(address=f"a{i}",volume_24h_usd=1,fees_24h_usd=1000-i)
            for i in range(100)
        ]
        first=[x["address"] for x in study._sample(rows)]
        second=[x["address"] for x in study._sample(list(reversed(rows)))]
        self.assertEqual(first,second)
        self.assertEqual(len(first),study.VOL_SAMPLE_PER_BUCKET)

    def test_protocol_forbids_wallet_inputs(self):
        import json
        body=json.loads(study.PROTOCOL.read_text())
        self.assertFalse(body["independence"]["consumes_wallet_review"])
        self.assertFalse(body["independence"]["consumes_wallet_pnl"])
        self.assertFalse(body["independence"]["consumes_profitable_operator_labels"])
        self.assertEqual(body["revision"],"1.1")


if __name__=="__main__":
    unittest.main()
