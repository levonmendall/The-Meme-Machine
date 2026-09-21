"""Deterministic regression for Meteora post-fill evidence recovery overlay."""
from unittest.mock import patch
from tests import solana_dlmm_independent_v1 as strategy

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

if __name__=="__main__":
    run()
    print("meteora_position_recovery_check: ok")
