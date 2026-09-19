import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import robinhood_research.ramses_extended_test as extended

from robinhood_research import BoundaryError
from robinhood_research.ramses_extended_test import (
    _exact_forced_horizon,
    _forced_finality_wait_budget,
    _frontier_progress,
    _frontier_scan_gate,
    _pick_forced_row,
    _screen_summary,
    _wait_for_forced_finality,
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
                # 7 second block spacing means there is no exact +60 block.
                return dict(
                    number=hex(block),
                    timestamp=hex(1000+(block-100)*7),
                )
        frontier=dict(number=hex(500),timestamp=hex(3800))
        selected,horizon=_exact_forced_horizon(
            Rpc(),100,1000,frontier
        )
        self.assertEqual(int(selected["timestamp"],16),1063)
        self.assertEqual(horizon["previous_timestamp"],1056)
        self.assertLess(horizon["previous_timestamp"],1060)
        self.assertGreaterEqual(horizon["selected_timestamp"],1060)

    def test_forced_finality_budget_tracks_live_lag_with_bounds(self):
        self.assertEqual(
            _forced_finality_wait_budget(1100,1000,1060),
            600,
        )
        self.assertEqual(
            _forced_finality_wait_budget(1500,1000,1060),
            1180,
        )
        self.assertEqual(
            _forced_finality_wait_budget(2000,1000,1060),
            1200,
        )

    def test_forced_finality_wait_tolerates_slow_progress_without_moving_target(self):
        class Clock:
            def __init__(self):
                self.now=0.0
            def time(self):
                return self.now
            def sleep(self,seconds):
                self.now+=float(seconds)

        class Rpc:
            def __init__(self):
                self.frontiers=[
                    dict(number=hex(101),timestamp=hex(1040)),
                    dict(number=hex(102),timestamp=hex(1050)),
                    dict(number=hex(103),timestamp=hex(1060)),
                ]
            def batch(self,calls,scope="connectivity"):
                self.assert_calls=calls
                return [
                    dict(number=hex(200),timestamp=hex(1500)),
                    dict(number=hex(100),timestamp=hex(1000)),
                ]
            def call(self,method,params,scope="connectivity"):
                if method!="eth_getBlockByNumber" or params!=["finalized",False]:
                    raise AssertionError((method,params,scope))
                return self.frontiers.pop(0)

        clock=Clock()
        frontier,meta=_wait_for_forced_finality(
            Rpc(),1000,clock=clock.time,sleeper=clock.sleep
        )
        self.assertEqual(int(frontier["timestamp"],16),1060)
        self.assertEqual(meta["target_timestamp"],1060)
        self.assertEqual(meta["observed_head_finalized_lag_seconds"],500)
        self.assertEqual(meta["wait_budget_seconds"],1180)
        self.assertEqual(meta["polls"],4)
        self.assertEqual(meta["progress_events"],3)
        self.assertEqual(meta["waited_seconds"],45.0)
        self.assertEqual(meta["horizon_unchanged_seconds"],60)

    def test_forced_finality_wait_rejects_frontier_regression(self):
        class Clock:
            def __init__(self):
                self.now=0.0
            def time(self):
                return self.now
            def sleep(self,seconds):
                self.now+=float(seconds)

        class Rpc:
            def batch(self,calls,scope="connectivity"):
                return [
                    dict(number=hex(200),timestamp=hex(1500)),
                    dict(number=hex(100),timestamp=hex(1000)),
                ]
            def call(self,method,params,scope="connectivity"):
                return dict(number=hex(99),timestamp=hex(999))

        clock=Clock()
        with self.assertRaisesRegex(
            BoundaryError,
            "extended_forced_finality_regression",
        ):
            _wait_for_forced_finality(
                Rpc(),1000,clock=clock.time,sleeper=clock.sleep
            )

    def test_finalized_frontier_gate_skips_duplicate_state(self):
        frontier=dict(
            number=hex(100),
            hash="0x"+"11"*32,
            timestamp=hex(1000),
            parentHash="0x"+"22"*32,
        )
        should,reason,identity=_frontier_scan_gate(
            (100,"0x"+"11"*32),
            frontier,
            now=120.0,
            last_scan_started=0.0,
            scan_interval=60,
        )
        self.assertFalse(should)
        self.assertEqual(reason,"frontier_unchanged")
        self.assertEqual(identity,(100,"0x"+"11"*32))

    def test_finalized_frontier_gate_defers_then_admits_advanced_state(self):
        frontier=dict(
            number=hex(101),
            hash="0x"+"33"*32,
            timestamp=hex(1001),
            parentHash="0x"+"11"*32,
        )
        should,reason,identity=_frontier_scan_gate(
            (100,"0x"+"11"*32),
            frontier,
            now=30.0,
            last_scan_started=0.0,
            scan_interval=60,
        )
        self.assertFalse(should)
        self.assertEqual(reason,"cadence_floor")
        should2,reason2,identity2=_frontier_scan_gate(
            (100,"0x"+"11"*32),
            frontier,
            now=60.0,
            last_scan_started=0.0,
            scan_interval=60,
        )
        self.assertTrue(should2)
        self.assertEqual(reason2,"frontier_advanced")
        self.assertEqual(identity2,identity)

    def test_finalized_frontier_progress_rejects_conflict_and_regression(self):
        prior=dict(
            number=hex(100),
            hash="0x"+"11"*32,
            timestamp=hex(1000),
            parentHash="0x"+"22"*32,
        )
        same=dict(prior)
        self.assertEqual(_frontier_progress(prior,same),"unchanged")
        advanced=dict(
            number=hex(101),
            hash="0x"+"33"*32,
            timestamp=hex(1001),
            parentHash=prior["hash"],
        )
        self.assertEqual(_frontier_progress(prior,advanced),"advanced")
        conflict=dict(prior,hash="0x"+"44"*32)
        with self.assertRaisesRegex(
            BoundaryError,
            "extended_finalized_frontier_conflict",
        ):
            _frontier_progress(prior,conflict)
        regressed=dict(
            number=hex(99),
            hash="0x"+"55"*32,
            timestamp=hex(999),
            parentHash="0x"+"66"*32,
        )
        with self.assertRaisesRegex(
            BoundaryError,
            "extended_finalized_frontier_regression",
        ):
            _frontier_progress(prior,regressed)

    def test_discovery_scans_only_initial_and_advanced_finalized_frontiers(self):
        class Clock:
            def __init__(self):
                self.now=0.0
            def monotonic(self):
                return self.now
            def sleep(self,seconds):
                self.now+=float(seconds)
            def wall(self):
                return 1000000.0+self.now

        def frontier(block,ts,byte,parent):
            return dict(
                number=hex(block),
                hash="0x"+byte*32,
                timestamp=hex(ts),
                parentHash="0x"+parent*32,
            )

        a=frontier(100,1000,"11","22")
        b=frontier(101,1001,"33","11")

        class Rpc:
            def __init__(self):
                self.rows=[a,a,b,b,b]
            def verify_chain(self):
                return 4663
            def call(self,method,params,scope="connectivity"):
                self.assert_method=(method,params,scope)
                if self.rows:
                    return dict(self.rows.pop(0))
                return dict(b)
            def telemetry(self):
                return dict(logical_requests=5,transport_requests=5)

        scans=[]
        def fake_scan(endpoint,**kwargs):
            pinned=kwargs["finalized_frontier"]
            scans.append((int(pinned["number"],16),pinned["hash"]))
            return dict(
                strategy_domain=STRATEGY_DOMAIN,
                policy_hash=POLICY_HASH,
                finalized_block=int(pinned["number"],16),
                finalized_hash=pinned["hash"],
                finalized_timestamp=int(pinned["timestamp"],16),
                finalized_frontier_source="pinned_external_finalized_header",
                rows=[],
                provider={},
            )

        clock=Clock()
        rpc=Rpc()
        with patch.object(extended,"BoundedMultiRpc",return_value=rpc), \
             patch.object(extended,"scan",side_effect=fake_scan), \
             patch.object(extended.time,"monotonic",side_effect=clock.monotonic), \
             patch.object(extended.time,"sleep",side_effect=clock.sleep), \
             patch.object(extended.time,"time",side_effect=clock.wall):
            result=extended.run(
                "https://example.invalid",
                discovery_seconds=75,
                discovery_interval_seconds=60,
            )

        self.assertEqual(
            scans,
            [(100,a["hash"]),(101,b["hash"])],
        )
        self.assertEqual(len(result["natural_screens"]),2)
        self.assertEqual(result["frontier_discovery"]["polls"],5)
        self.assertEqual(result["frontier_discovery"]["advances"],1)
        self.assertEqual(result["frontier_discovery"]["expensive_scans"],2)
        self.assertEqual(
            result["frontier_discovery"]["duplicate_frontier_polls_skipped"],
            1,
        )
        self.assertEqual(
            result["frontier_discovery"]["cadence_deferred_polls"],
            2,
        )
        self.assertEqual(clock.now,75.0)
        self.assertEqual(
            result["status"],
            "natural_discovery_complete_no_qualifier",
        )


if __name__=="__main__":
    unittest.main()
