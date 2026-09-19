import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import dlmm_profitable_operator_rules as rules


def derivation(min_clusters=3):
    return {
        "revision":"1.0",
        "core_family":{
            "independent_cluster_support_required":2/3,
            "minimum_independent_clusters":min_clusters,
        },
        "context_dimensions":{
            "pool_age_seconds":[],
            "pre_entry_60m_volume_usd":[],
            "pre_entry_5m_log_return_volatility":[],
            "entry_dynamic_fee_bps_observed":[],
        },
    }


def wallet(name,family="curve",side="one_sided",width=70,center=0,hold=500,
           rebalance=0,after=10.0,exact=True):
    return {
        "wallet":name,
        "after_network_cost_pnl_usd":after,
        "capital_at_risk_exact":exact,
        "entry_exit_profiles":[{
            "entry":{
                "strategy_family":family,
                "one_sided":side=="one_sided",
                "two_sided":side=="two_sided",
                "width_bins":width,
                "center_active_offset_bins":center,
            },
            "hold_seconds":hold,
            "rebalance_count":rebalance,
        }],
    }


class ProfitableOperatorRuleTests(unittest.TestCase):
    def test_wallet_behavior_uses_frozen_buckets(self):
        p=rules.wallet_behavior(wallet("a",width=70,center=0,hold=500,rebalance=1))
        self.assertEqual(p["vote"]["distribution_family"],"curve")
        self.assertEqual(p["vote"]["sidedness"],"one_sided")
        self.assertEqual(p["vote"]["width_bucket"],">50")
        self.assertEqual(p["vote"]["active_bin_placement_bucket"],"centered")
        self.assertEqual(p["vote"]["rebalance_bucket"],"active")
        self.assertEqual(p["vote"]["hold_bucket"],"<15m")

    def test_direct_fleet_counts_as_one_cluster_vote(self):
        deep={
            "kind":"dlmm_profitable_operator_deep_reconstruction_v1",
            "wallets":[wallet("a"),wallet("b"),wallet("c"),wallet("d")],
            "operator_clusters":[
                {"cluster_id":"fleet","wallets":["a","b"]},
                {"cluster_id":"c","wallets":["c"]},
                {"cluster_id":"d","wallets":["d"]},
            ],
        }
        protocol={"protocol_revision":"1.2"}
        with tempfile.TemporaryDirectory() as td:
            deep_path=Path(td)/"deep.json";deep_path.write_text(json.dumps(deep))
            protocol_path=Path(td)/"protocol.json";protocol_path.write_text(json.dumps(protocol))
            derivation_path=Path(td)/"derivation.json";derivation_path.write_text(json.dumps(derivation(3)))
            out_path=Path(td)/"out.json"
            with patch.object(rules,"PROTOCOL",protocol_path),patch.object(rules,"DERIVATION_PROTOCOL",derivation_path),patch.object(rules,"OUT",out_path):
                report=rules.derive(deep_path)
        self.assertEqual(report["qualifying_independent_clusters"],3)
        self.assertEqual(len(report["candidate_rule_proposals"]),1)
        self.assertEqual(
            report["candidate_rule_proposals"][0]["independent_cluster_count"],3)

    def test_two_of_three_support_passes_and_one_of_three_does_not(self):
        base=wallet("a")
        b=wallet("b")
        c=wallet("c",family="spot")
        deep={
            "kind":"dlmm_profitable_operator_deep_reconstruction_v1",
            "wallets":[base,b,c],
            "operator_clusters":[
                {"cluster_id":"a","wallets":["a"]},
                {"cluster_id":"b","wallets":["b"]},
                {"cluster_id":"c","wallets":["c"]},
            ],
        }
        protocol={"protocol_revision":"1.2"}
        with tempfile.TemporaryDirectory() as td:
            dp=Path(td)/"d";dp.write_text(json.dumps(deep))
            pp=Path(td)/"p";pp.write_text(json.dumps(protocol))
            dp2=Path(td)/"dp";dp2.write_text(json.dumps(derivation(2)))
            op=Path(td)/"o"
            with patch.object(rules,"PROTOCOL",pp),patch.object(rules,"DERIVATION_PROTOCOL",dp2),patch.object(rules,"OUT",op):
                report=rules.derive(dp)
        self.assertEqual(len(report["candidate_rule_proposals"]),1)
        self.assertEqual(
            report["candidate_rule_proposals"][0]["family"]["distribution_family"],
            "curve")

    def test_rule_freeze_requires_ready_pre_outcome_proposals(self):
        protocol={"protocol_revision":"1.2"}
        deriv={"revision":"1.0","prospective_test":{"paper_only":True}}
        proposals={
            "kind":"dlmm_profitable_operator_rule_proposals_v1",
            "status":"candidate_rules_ready_to_freeze_before_prospective_test",
            "protocol_revision":"1.2",
            "derivation_protocol_revision":"1.0",
            "prospective_outcomes_read":False,
            "candidate_rule_proposals":[{"family":{"distribution_family":"curve"}}],
        }
        with tempfile.TemporaryDirectory() as td:
            pp=Path(td)/"p";pp.write_text(json.dumps(protocol))
            dp=Path(td)/"d";dp.write_text(json.dumps(deriv))
            source=Path(td)/"source";source.write_text(json.dumps(proposals))
            output=Path(td)/"frozen"
            with patch.object(rules,"PROTOCOL",pp),patch.object(
                    rules,"DERIVATION_PROTOCOL",dp):
                frozen=rules.freeze_proposals(source,output)
                self.assertEqual(frozen["status"],"frozen_pre_prospective")
                self.assertFalse(frozen["prospective_outcomes_read_before_freeze"])
                self.assertEqual(frozen["rule_count"],1)
                bad=dict(proposals);bad["prospective_outcomes_read"]=True
                source.write_text(json.dumps(bad))
                with self.assertRaisesRegex(RuntimeError,"outcome_leakage"):
                    rules.freeze_proposals(source,output)

    def test_negative_or_inexact_wallet_cannot_support_rule(self):
        deep={
            "kind":"dlmm_profitable_operator_deep_reconstruction_v1",
            "wallets":[wallet("a"),wallet("b",after=-1),wallet("c",exact=False)],
            "operator_clusters":[
                {"cluster_id":"a","wallets":["a"]},
                {"cluster_id":"b","wallets":["b"]},
                {"cluster_id":"c","wallets":["c"]},
            ],
        }
        protocol={"protocol_revision":"1.2"}
        with tempfile.TemporaryDirectory() as td:
            dp=Path(td)/"d";dp.write_text(json.dumps(deep))
            pp=Path(td)/"p";pp.write_text(json.dumps(protocol))
            dp2=Path(td)/"dp";dp2.write_text(json.dumps(derivation(3)))
            out=Path(td)/"o"
            with patch.object(rules,"PROTOCOL",pp),patch.object(rules,"DERIVATION_PROTOCOL",dp2),patch.object(rules,"OUT",out):
                report=rules.derive(dp)
        self.assertEqual(report["qualifying_independent_clusters"],1)
        self.assertEqual(report["candidate_rule_proposals"],[])


if __name__=="__main__":
    unittest.main()
