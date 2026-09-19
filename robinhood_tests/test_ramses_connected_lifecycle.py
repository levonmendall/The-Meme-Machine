import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import robinhood_research.ramses_all_pool_lifecycle as lifecycle
from robinhood_research.ramses_all_pool_lifecycle import (
    _canonicalize_selected_row,
    _frozen_prestate,
    aggregate_segments,
    compact_lifecycle_result,
    select_qualifier,
)
from robinhood_research.ramses_strategy import (
    POLICY_HASH,
    STRATEGY_DOMAIN,
    STRATEGY_VERSION,
)
from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger


def _freeze():
    proposal = dict(capital_employed=100)
    digest = hashlib.sha256(
        json.dumps([proposal], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return dict(
        proposal_hash=digest,
        proposals=[proposal],
        frozen=True,
        allocation_authority=False,
        strategy_domain=STRATEGY_DOMAIN,
        strategy_version=STRATEGY_VERSION,
        policy_hash=POLICY_HASH,
    )


def _decision(qualified=True):
    return dict(
        mode="fee_pulse",
        qualified=qualified,
        allocation_authority=False,
        strategy_domain=STRATEGY_DOMAIN,
        strategy_version=STRATEGY_VERSION,
        policy_hash=POLICY_HASH,
        freeze=_freeze(),
    )


class RamsesConnectedLifecycleTests(unittest.TestCase):
    def test_first_ranked_genuine_qualifier_is_selected(self):
        screen = dict(
            strategy_domain=STRATEGY_DOMAIN,
            rows=[
                dict(pool="0x"+"11"*20, decision=_decision(False)),
                dict(pool="0x"+"22"*20, decision=_decision(True)),
                dict(pool="0x"+"33"*20, decision=_decision(True)),
            ],
        )
        self.assertEqual(select_qualifier(screen)["pool"], "0x"+"22"*20)

    def test_no_qualifier_returns_none(self):
        screen = dict(
            strategy_domain=STRATEGY_DOMAIN,
            rows=[dict(pool="0x"+"11"*20, decision=_decision(False))],
        )
        self.assertIsNone(select_qualifier(screen))

    def test_segment_pnl_is_aggregated_after_rebalances(self):
        segments = [
            dict(
                initial_cost_basis=1000,
                pnl=dict(
                    fee_pnl_quote=20,
                    inventory_or_directional_pnl_quote=-5,
                    execution_cost_quote=3,
                    gross_result_quote=15,
                    net_result_quote=12,
                    unresolved_inventory=None,
                ),
            ),
            dict(
                initial_cost_basis=1012,
                pnl=dict(
                    fee_pnl_quote=10,
                    inventory_or_directional_pnl_quote=2,
                    execution_cost_quote=2,
                    gross_result_quote=12,
                    net_result_quote=10,
                    unresolved_inventory=None,
                ),
            ),
        ]
        got = aggregate_segments(segments)
        self.assertEqual(got["segments"], 2)
        self.assertEqual(got["rebalances"], 1)
        self.assertEqual(got["fee_pnl_quote"], 30)
        self.assertEqual(got["inventory_or_directional_pnl_quote"], -3)
        self.assertEqual(got["execution_cost_quote"], 5)
        self.assertEqual(got["net_result_quote"], 22)
        self.assertEqual(got["after_cost_return_bps"], 220)

    def test_ledger_persists_monitor_segment_and_rebalance_checkpoints(self):
        fd, path = tempfile.mkstemp(prefix="ramses-connected-", suffix=".sqlite")
        os.close(fd)
        os.unlink(path)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        ledger = RamsesStrategyLedger(
            path, paper_capital=1000, quote_asset="0x"+"44"*20
        )
        decision = _decision(True)
        ledger.reserve(
            "id", pool="0x"+"55"*20, decision=decision, at=1
        )
        ledger.open("id", at=2)
        ledger.checkpoint(
            "id", action="monitor", detail=dict(action="hold"), at=3
        )
        ledger.checkpoint(
            "id", action="segment_close",
            detail=dict(segment=0, exit_reason="bin_displacement"), at=4
        )
        ledger.checkpoint(
            "id", action="rebalance",
            detail=dict(proposal_hash="a"*64), at=5
        )
        body = ledger.position("id")
        self.assertEqual(body["segments_closed"], 1)
        self.assertEqual(body["rebalances"], 1)
        self.assertEqual(body["proposal_hash"], "a"*64)
        ledger.close()

    def test_connected_entrypoint_does_not_call_legacy_native_selector(self):
        root = Path(__file__).parents[1] / "robinhood_research"
        connected = (root / "ramses_all_pool_lifecycle.py").read_text()
        sample = (root / "ramses_strategy_sample.py").read_text()
        self.assertNotIn("from .ramses_capture import run", connected)
        self.assertNotIn("ramses_capture.run", connected)
        self.assertNotIn("ramses_capture", sample)
        self.assertIn("ramses_all_pool_lifecycle", sample)

    def test_canonical_history_replaces_scanner_count_mismatch(self):
        pool="0x"+"66"*20
        tx1="0x"+"a1"*32
        tx2="0x"+"a2"*32
        bh1="0x"+"b1"*32
        bh2="0x"+"b2"*32
        def event(block,tx,bh,log_index):
            return dict(
                address=pool,
                blockNumber=hex(block),
                blockHash=bh,
                transactionHash=tx,
                transactionIndex="0x0",
                logIndex=hex(log_index),
                removed=False,
                topics=["0x"+"01"*32],
                data="0x",
            )
        e1=event(100,tx1,bh1,0)
        e2=event(101,tx2,bh2,0)

        class Rpc:
            def batch(self,calls,scope="connectivity"):
                raise AssertionError(calls)
            def receipts(self,identities,scope="connectivity"):
                out=[]
                for tx,block_hash in identities:
                    e=e1 if tx==tx1 else e2
                    self.assert_equal_block = block_hash == e["blockHash"]
                    if not self.assert_equal_block:
                        raise AssertionError((block_hash,e["blockHash"]))
                    out.append(dict(
                        transactionHash=tx,
                        blockHash=e["blockHash"],
                        transactionIndex=e["transactionIndex"],
                        status="0x1",
                        logs=[e],
                    ))
                return out
            def blocks(self,blocks,scope="connectivity"):
                out=[]
                for block in blocks:
                    e=e1 if block==100 else e2
                    out.append(dict(
                        number=hex(block),
                        hash=e["blockHash"],
                        timestamp=hex(1000+block),
                        parentHash="0x"+"00"*32,
                    ))
                return out

        row=dict(
            pool=pool,
            prehistory=[dict(
                block=100,
                block_hash=bh1,
                transaction_hash=tx1,
                transaction_index=0,
                log_index=0,
                args=dict(id=1,amountsIn="0x0"),
            )],
        )
        screen=dict(lookback_start_block=100,finalized_block=101)
        decoded1=dict(name="Swap",args=dict(id=1,amountsIn="0x0"))
        decoded2=dict(name="Swap",args=dict(id=2,amountsIn="0x0"))
        with patch.object(lifecycle,"_batch_logs",return_value=[e1,e2]), \
             patch.object(lifecycle,"decode_ramses_event",side_effect=[decoded1,decoded2]):
            history,auth=lifecycle._canonical_preentry_history(Rpc(),row,screen)
        self.assertEqual(len(history),2)
        self.assertEqual(auth["scanner_swap_logs"],1)
        self.assertEqual(auth["swap_logs"],2)
        self.assertFalse(auth["identity_match"])
        self.assertEqual(auth["canonical_only"],1)

    def test_frozen_prestate_requires_exact_finalized_identity(self):
        state = dict(
            active=7,
            step=5,
            bins={7: dict(reserves=[1, 2], supply=3)},
        )
        row = dict(
            prestate=state,
            prestate_block=123,
            prestate_block_hash="0x" + "ab" * 32,
            prestate_timestamp=456,
        )
        screen = dict(
            finalized_block=123,
            finalized_hash="0x" + "ab" * 32,
            finalized_timestamp=456,
        )
        got = _frozen_prestate(row, screen)
        self.assertEqual(got, state)
        self.assertIsNot(got, state)
        bad = dict(row, prestate_block_hash="0x" + "cd" * 32)
        with self.assertRaisesRegex(
            lifecycle.BoundaryError,
            "frozen_prestate_identity",
        ):
            _frozen_prestate(bad, screen)

    def test_canonical_reclassification_reuses_scanner_prestate_without_state_rpc(self):
        state = dict(
            active=7,
            step=5,
            bins={7: dict(reserves=[10, 20], supply=30)},
        )
        row = dict(
            pool="0x" + "66" * 20,
            quote_side="y",
            prestate=state,
            prehistory=[dict(block=1)],
            prestate_block=123,
            prestate_block_hash="0x" + "ab" * 32,
            prestate_timestamp=456,
            paper_capital_quote_raw=100,
            features=dict(turnover_bps=1, total_fee_rate=1),
        )
        screen = dict(
            finalized_block=123,
            finalized_hash="0x" + "ab" * 32,
            finalized_timestamp=456,
            lookback_start_block=100,
            rows=[row],
        )
        history = [dict(
            block=120,
            block_hash="0x" + "ef" * 32,
            transaction_hash="0x" + "11" * 32,
            transaction_index=0,
            log_index=0,
            args=dict(id=7, amountsIn="0x0"),
        )]
        decision = dict(
            mode="no_trade",
            qualified=False,
            allocation_authority=False,
            strategy_domain=STRATEGY_DOMAIN,
            strategy_version=STRATEGY_VERSION,
            policy_hash=POLICY_HASH,
            reasons=["test"],
        )
        with patch.object(
            lifecycle,
            "_canonical_preentry_history",
            return_value=(history, dict(authenticated=True)),
        ), patch.object(
            lifecycle,
            "pool_features",
            return_value=dict(turnover_bps=2, total_fee_rate=2),
        ), patch.object(
            lifecycle,
            "classify_pool",
            return_value=decision,
        ) as classify:
            canonical, auth = _canonicalize_selected_row(
                object(), row, screen, costs_by_pool={}, signals_by_pool={}
            )
        self.assertEqual(canonical["prestate"], state)
        self.assertEqual(canonical["prehistory"], history)
        self.assertEqual(classify.call_args.args[0], state)
        self.assertTrue(auth["prestate_reused_from_scanner"])
        self.assertFalse(auth["prestate_rpc_refetch"])
        self.assertEqual(auth["prestate_block"], 123)

    def test_compact_lifecycle_report_strips_selector_prestate(self):
        result = dict(
            initial_screen=dict(
                rows=[dict(
                    pool="0x" + "77" * 20,
                    prestate=dict(
                        active=7,
                        step=5,
                        bins={7: dict(reserves=[1, 2], supply=3)},
                    ),
                    prehistory=[dict(block=1)],
                    prestate_block=123,
                    prestate_block_hash="0x" + "ab" * 32,
                    prestate_timestamp=456,
                )],
            ),
        )
        public = compact_lifecycle_result(result)
        self.assertNotIn("prestate", public["initial_screen"]["rows"][0])
        self.assertNotIn("prehistory", public["initial_screen"]["rows"][0])
        self.assertFalse(public["selector_prestate_persisted_in_artifact"])


if __name__ == "__main__":
    unittest.main()
