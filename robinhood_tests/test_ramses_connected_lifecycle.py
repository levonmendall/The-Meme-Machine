import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import robinhood_research.ramses_all_pool_lifecycle as lifecycle
from robinhood_research.ramses_all_pool_lifecycle import (
    aggregate_segments,
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
                if calls and calls[0][0]=="eth_getTransactionReceipt":
                    out=[]
                    for _method,params in calls:
                        tx=params[0]
                        e=e1 if tx==tx1 else e2
                        out.append(dict(
                            transactionHash=tx,
                            blockHash=e["blockHash"],
                            transactionIndex=e["transactionIndex"],
                            status="0x1",
                            logs=[e],
                        ))
                    return out
                if calls and calls[0][0]=="eth_getBlockByNumber":
                    out=[]
                    for _method,params in calls:
                        block=int(params[0],16)
                        e=e1 if block==100 else e2
                        out.append(dict(
                            number=hex(block),
                            hash=e["blockHash"],
                            timestamp=hex(1000+block),
                            parentHash="0x"+"00"*32,
                        ))
                    return out
                raise AssertionError(calls)

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


if __name__ == "__main__":
    unittest.main()
