"""Deterministic regression for Meteora post-fill evidence recovery overlay."""
from unittest.mock import patch
from tests import solana_dlmm_independent_v1 as strategy
from meme_machine.dlmm_independent_accounting import PaperBook
from meme_machine.store import digest
import tempfile
from pathlib import Path

def run():
    adapter=object()
    current={"slot":100,"time":1000}
    pacer=object();rpcs=[];broker=object()
    calls=[]
    tape=object()
    terminal={"slot":120,"time":1024}
    def observe(*args,**kwargs):
        calls.append(args[2])
        if len(calls)==1:
            return (
                {"verified":False,"reason":"solana_dlmm_transaction_hydration_incomplete"},
                None,current,current,adapter,
            )
        return (
            {"verified":True,"reason":None},
            tape,terminal,current,adapter,
        )
    with patch.object(strategy,"_observe_window",side_effect=observe), \
         patch.object(strategy,"_rotate",side_effect=lambda active,*_args: active), \
         patch.object(strategy,"_runtime_expired",return_value=False), \
         patch.object(strategy,"_stage") as stage:
        phase,got_tape,got_terminal,effective,got_adapter,recoveries=(
            strategy._recover_position_observation(
                adapter,"pool",current,12,pacer,rpcs,9999999999,broker))
    assert phase["verified"] is True
    assert got_tape is tape and got_terminal is terminal and effective is current
    assert got_adapter is adapter
    assert calls == [current,current], calls
    assert recoveries == [{"attempt":1,"reason":"solana_dlmm_transaction_hydration_incomplete"}]
    assert stage.call_count == 1

    calls.clear()
    def structural(*args,**kwargs):
        calls.append(args[2])
        return (
            {"verified":False,"reason":"solana_dlmm_interval_evidence_bound"},
            None,current,current,adapter,
        )
    with patch.object(strategy,"_observe_window",side_effect=structural), \
         patch.object(strategy,"_runtime_expired",return_value=False), \
         patch.object(strategy,"_stage") as stage:
        phase,*rest=strategy._recover_position_observation(
            adapter,"pool",current,12,pacer,rpcs,9999999999,broker)
    assert phase["verified"] is False
    assert calls == [current]
    assert rest[-1] == []
    assert stage.call_count == 0

    with tempfile.TemporaryDirectory() as td:
        policy={}
        book=PaperBook(Path(td)/"paper.sqlite3",
            run_id="recovery-check",policy_hash=digest(policy),capital=1_000_000_000)
        identity=book.identity()
        capital=100_000_000;entry_cost=200_000;exit_cost=200_000
        book.append(identity,"reserve",dict(
            amount=capital+entry_cost+exit_cost,pool="pool",
            policy_hash=digest(policy),strategy_evidence_hash="e"))
        book.append(identity,"entry",dict(
            capital=capital,entry_cost=entry_cost,exit_cost=exit_cost,
            entry_state={"slot":1},position={"paper":True},features={},
            policy=policy,mark=dict(
                ending_sol_lamports=capital,
                pnl_lamports=-(entry_cost+exit_cost))))
        book.append(identity,"writeoff",dict(
            reason="dlmm_rebalance_liquidity_requires_position_state:123"))
        rec=book.reconcile()
        assert rec["unsettled"] == 0
        assert rec["open_positions"] == 0
        assert rec["writeoffs"] == 1
        assert rec["settled"] == 0
        assert rec["reserved"] == 0
        assert rec["realized_pnl_lamports"] == -(capital+entry_cost)
        assert rec["marked_equity"] == rec["cash"]

if __name__=="__main__":
    run()
    print("meteora_position_recovery_check: ok")
