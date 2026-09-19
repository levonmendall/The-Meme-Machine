import hashlib
import json
import os
import tempfile
import unittest

from robinhood_research import BoundaryError
from robinhood_research.ramses_extended_test import (
    _exact_forced_horizon,
    _pick_forced_row,
    _screen_summary,
)
from robinhood_research.ramses_strategy import (
    POLICY_HASH,
    STRATEGY_DOMAIN,
    STRATEGY_VERSION,
)
from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger


def _freeze(capital=100):
    proposal=dict(capital_employed=capital)
    digest=hashlib.sha256(
        json.dumps([proposal],sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    return dict(
        frozen=True,
        allocation_authority=False,
        strategy_domain=STRATEGY_DOMAIN,
        strategy_version=STRATEGY_VERSION,
        policy_hash=POLICY_HASH,
        proposal_hash=digest,
        proposals=[proposal],
    )


def _decision(*,qualified=False,capital=100):
    return dict(
        mode=("fee_pulse" if qualified else "no_trade"),
        qualified=qualified,
        allocation_authority=False,
        strategy_domain=STRATEGY_DOMAIN,
        strategy_version=STRATEGY_VERSION,
        policy_hash=POLICY_HASH,
        freeze=_freeze(capital),
        reasons=([] if qualified else ["flow_imbalance"]),
    )


class RamsesExtendedMarketTests(unittest.TestCase):
    def _path(self):
        fd,path=tempfile.mkstemp(prefix="ramses-extended-",suffix=".sqlite")
        os.close(fd);os.unlink(path)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_screen_summary_preserves_rejections(self):
        screen=dict(
            finalized_block=10,
            finalized_timestamp=1000,
            factory_pool_count=277,
            pools_with_recent_swaps=1,
            state_complete_pools=1,
            rows=[dict(
                pool="0x"+"11"*20,
                swap_count=4,
                features=dict(
                    turnover_bps=123,
                    turnover_percentile_bps=10000,
                    fee_percentile_bps=9000,
                    volume_acceleration_milli=2500,
                    chop_ratio_milli=500,
                    flow_imbalance_bps=9000,
                ),
                decision=_decision(qualified=False),
            )],
            provider=dict(requests=1),
        )
        got=_screen_summary(screen)
        self.assertEqual(got["factory_pool_count"],277)
        self.assertEqual(got["qualified"],[])
        self.assertEqual(got["rows"][0]["reasons"],["flow_imbalance"])

    def test_forced_row_uses_latest_screen_and_frozen_proposal(self):
        first=dict(rows=[dict(pool="0x"+"11"*20,decision=_decision())])
        second=dict(rows=[dict(pool="0x"+"22"*20,decision=_decision())])
        screen,row=_pick_forced_row([first,second])
        self.assertIs(screen,second)
        self.assertEqual(row["pool"],"0x"+"22"*20)

    def test_forced_machinery_reservation_is_strategy_ineligible(self):
        path=self._path()
        ledger=RamsesStrategyLedger(
            path,paper_capital=1000,quote_asset="0x"+"44"*20
        )
        body=ledger.reserve_forced_machinery(
            "forced",
            pool="0x"+"55"*20,
            decision=_decision(qualified=False,capital=100),
            at=1,
        )
        self.assertTrue(body["forced_machinery_test"])
        self.assertFalse(body["strategy_evidence_eligible"])
        self.assertFalse(body["allocation_authority"])
        self.assertEqual(body["status"],"reserved")
        ledger.close()

    def test_forced_machinery_rejects_foreign_domain(self):
        path=self._path()
        ledger=RamsesStrategyLedger(
            path,paper_capital=1000,quote_asset="0x"+"44"*20
        )
        decision=_decision()
        decision["strategy_domain"]="continuation-v1-robinhood"
        with self.assertRaisesRegex(BoundaryError,"foreign_forced_machinery_decision"):
            ledger.reserve_forced_machinery(
                "forced",pool="0x"+"55"*20,decision=decision,at=1
            )
        ledger.close()

    def test_exact_forced_horizon_uses_earliest_finalized_crossing(self):
        class Rpc:
            def call(self,method,params,scope="forward"):
                if method!="eth_getBlockByNumber":
                    raise AssertionError((method,params,scope))
                block=int(params[0],16)
                return dict(
                    number=hex(block),
                    timestamp=hex(1000+(block-100)*2),
                )
        frontier=dict(number=hex(500),timestamp=hex(1800))
        selected,horizon=_exact_forced_horizon(
            Rpc(),100,1000,frontier
        )
        self.assertEqual(int(selected["number"],16),130)
        self.assertEqual(int(selected["timestamp"],16),1060)
        self.assertEqual(horizon["selected_elapsed_seconds"],60)
        self.assertEqual(horizon["previous_elapsed_seconds"],58)
        self.assertTrue(horizon["earliest_finalized_at_or_after_target"])
        self.assertLess(horizon["selected_block"],500)

    def test_exact_forced_horizon_accepts_first_block_after_target(self):
        class Rpc:
            def call(self,method,params,scope="forward"):
                block=int(params[0],16)
                # 3 second block spacing means there is no exact +60 block.
                return dict(
                    number=hex(block),
                    timestamp=hex(1000+(block-100)*3),
                )
        frontier=dict(number=hex(500),timestamp=hex(2200))
        selected,horizon=_exact_forced_horizon(
            Rpc(),100,1000,frontier
        )
        self.assertEqual(int(selected["timestamp"],16),1060)
        self.assertLess(horizon["previous_timestamp"],1060)
        self.assertGreaterEqual(horizon["selected_timestamp"],1060)


if __name__=="__main__":
    unittest.main()
