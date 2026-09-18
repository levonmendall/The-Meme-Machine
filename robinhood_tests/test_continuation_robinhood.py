from dataclasses import replace
import unittest

from robinhood_research.continuation_robinhood import (
    EXIT_POLICY, POLICY, REFERENCE_ENTRY_WEI, THRESHOLDS, TRANSLATION_SNAPSHOT,
    qualification_vector,
)
from robinhood_research.pons import CurveState

ZERO="0x0000000000000000000000000000000000000000"
TOKEN="0x"+"11"*20
CURVE="0x"+"22"*20
CREATOR="0x"+"33"*20
NOM="0x"+"44"*20


def state(**kw):
    base=CurveState(
        quote_reserve=2*10**18,token_reserve=800*10**24,real_quote=10**18,
        reserved_tokens=100*10**24,fee_bps=100,creator_tax_bps=0,
        graduated=False,launched_at=0,snipe_start_bps=0,snipe_seconds=1,timestamp=100,
    )
    return replace(base,**kw)


def record():
    return dict(
        token=TOKEN,curve=CURVE,deployer=CREATOR,creatorFeeRecipient=CREATOR,
        pairToken=ZERO,exists=True,
    )


def nomination():
    return dict(
        identity="n",side="buy",quote=10**16,tokens=4*10**24,event_at=100,
        actor=NOM,recipient=NOM,group=NOM,
    )


def events():
    rows=[]
    for i in range(3):
        a="0x"+f"{80+i:040x}"
        rows.append(dict(
            identity=f"b{i}",side="buy",quote=2*10**16,tokens=8*10**24,
            event_at=100,actor=a,recipient=a,group=a,
        ))
    return rows


def vector(**overrides):
    args=dict(
        state=state(),record=record(),nomination=nomination(),events=events(),
        concentration_bps=2000,concentration_meta={"complete":True},
        current_snipe_bps=0,roundtrip_gas_wei=10**12,asof=100,asof_block=1,
    )
    args.update(overrides)
    return qualification_vector(**args)


class FrozenRobinhoodContinuationTests(unittest.TestCase):
    def test_translation_and_exit_policy_are_frozen(self):
        self.assertEqual(POLICY,"continuation-v1-robinhood")
        self.assertEqual(THRESHOLDS,dict(
            max_concentration_bps=3500,
            min_real_quote_wei=429742223375869849,
            max_evidence_events=100,
            min_independent_groups=3,
            min_independent_net_buy_wei=42974222337586985,
            max_price_extension_bps=12000,
            max_roundtrip_loss_bps=500,
        ))
        self.assertEqual(EXIT_POLICY["take_profit_bps"],1500)
        self.assertEqual(EXIT_POLICY["risk_bps"],-1000)
        self.assertEqual(EXIT_POLICY["timeout_seconds"],900)
        self.assertEqual(TRANSLATION_SNAPSHOT["sol_usd"],"112.58")
        self.assertEqual(TRANSLATION_SNAPSHOT["eth_usd"],"2619.71")
        self.assertEqual(REFERENCE_ENTRY_WEI,9543041023624753)

    def test_complete_vector_can_pass_unchanged_gates(self):
        v=vector()
        self.assertTrue(v["complete"])
        self.assertTrue(v["current_threshold_pass"])
        self.assertEqual(v["qualification"],"qualified")
        self.assertEqual(v["independent_buyer_groups"],3)

    def test_three_independent_groups_is_not_relaxed(self):
        e=events()[:2]
        v=vector(events=e)
        self.assertIn("independent_demand",v["all_rejections"])

    def test_nomination_and_creator_do_not_confirm_themselves(self):
        e=events()
        e[0]=dict(e[0],actor=NOM,recipient=NOM,group=NOM)
        e[1]=dict(e[1],actor=CREATOR,recipient=CREATOR,group=CREATOR)
        v=vector(events=e)
        self.assertEqual(v["independent_buyer_groups"],1)
        self.assertIn("independent_demand",v["all_rejections"])

    def test_concentration_liquidity_and_capacity_are_exact(self):
        self.assertIn("concentration",vector(concentration_bps=3501)["all_rejections"])
        low=state(real_quote=THRESHOLDS["min_real_quote_wei"]-1)
        self.assertIn("exit_liquidity",vector(state=low)["all_rejections"])
        too_many=events()*34
        self.assertEqual(len(too_many),102)
        self.assertIn("evidence_capacity",vector(events=too_many)["all_rejections"])

    def test_price_extension_is_not_relaxed(self):
        n=nomination();n["tokens"]*=2
        v=vector(nomination=n)
        self.assertIn("extended_price",v["all_rejections"])

    def test_roundtrip_cost_unavailable_fails_closed(self):
        v=vector(roundtrip_gas_wei=10**18)
        self.assertIn("roundtrip_cost",v["all_rejections"])

    def test_non_native_pair_is_not_silently_translated(self):
        r=record();r["pairToken"]="0x"+"99"*20
        self.assertIn("unsupported_pair_quote",vector(record=r)["all_rejections"])


if __name__=="__main__":
    unittest.main()
