"""Prove terminal-state Ramses paper P&L is equivalent to full exact replay.

The project paper model is a frozen non-impact overlay. Once exact replay has proven
terminal equality, gross paper P&L depends on the frozen entry proposal, exact
terminal bin state, and exact executable unwind. This diagnostic reconstructs the
12 previously certified 5-minute variants from only entry/exit archive state and
requires bit-for-bit equality of the economic fields used by strategy evaluation.
"""
from __future__ import annotations
import json, os
from pathlib import Path

from . import BoundaryError
from .abi import calldata
from .identity import load
from .ramses import (
    authenticate_pool, freeze_proposals, paper_outcome, paper_position,
    price, quote_value, state, values,
)
from .ramses_capture import BoundedMultiRpc
from .ramses_all_pool_lifecycle import _snapshot, _unwind
from .ramses_historical_quiet_mint_counterfactual import one_freeze, USDG

SRC=Path("ramses-historical-exact-replay-probe.json")
OUT=Path("ramses-terminal-state-equivalence.json")
WIDTHS=(1,2,3,5)
DEPTH_BPS=50

def main():
    exact=json.loads(SRC.read_text())
    if exact.get("kind")!="ramses_dlmm_historical_exact_replay_probe_v1":
        raise RuntimeError("terminal_equivalence_source_kind")
    endpoint=os.environ.get("MM_ROBINHOOD_DLMM_RPC_URL") or os.environ.get("MM_ROBINHOOD_READ_RPC_URL") or ""
    rpc=BoundedMultiRpc(
        endpoint,max_sessions=120,batch_size=16,batch_pause=.20,
        rate_retries=3,rate_cooldown=4.0,adaptive_batch_floor=2,
    )
    rpc.verify_chain()
    factory=load("ramses_factory")["address"]
    results=[]; mismatches=[]
    for candidate in exact.get("candidates") or []:
        pool=candidate["pool"].lower();entry=int(candidate["entry_block"]);end=int(candidate["end_block"])
        entry_at=int(candidate["entry_timestamp"])
        member,code,active_raw,step_raw=rpc.batch([
            ("eth_call",[dict(to=factory,data=calldata("isPool(address)",pool)),hex(entry)]),
            ("eth_getCode",[pool,hex(entry)]),
            ("eth_call",[dict(to=pool,data=calldata("getActiveId()")),hex(entry)]),
            ("eth_call",[dict(to=pool,data=calldata("getBinStep()")),hex(entry)]),
        ],scope="terminal_equivalence")
        if int(member,16)!=1: raise BoundaryError("terminal_equivalence_membership")
        auth=authenticate_pool(code,factory_member=True)
        active=values(active_raw)[0];step=values(step_raw)[0]
        if auth["token_y"].lower()!=USDG: raise BoundaryError("terminal_equivalence_quote")
        if active!=int(candidate["active_bin"]) or step!=int(candidate["bin_step_bps"]):
            raise BoundaryError("terminal_equivalence_entry_identity")
        bins=list(range(active-max(WIDTHS),active+max(WIDTHS)+1))
        pre=state(_snapshot(rpc,pool,entry,bins,initial=True))
        active_liq=quote_value(pre["bins"][active]["reserves"],price(active,step),"y")
        capital=max(1,active_liq*DEPTH_BPS//10000)
        if active_liq!=int(candidate["active_liquidity_quote_raw"]) or capital!=int(candidate["capital_quote_raw"]):
            raise BoundaryError("terminal_equivalence_capital")
        freeze=freeze_proposals(
            pre,capital,quote_side="y",entry_timestamp=entry_at,
            prehistory=None,gas_costs=None,widths=WIDTHS,
        )
        terminal=state(_snapshot(rpc,pool,end,bins,initial=False))
        if terminal["step"]!=step: raise BoundaryError("terminal_equivalence_step")
        expected={int(v["width"]):v for v in candidate.get("variants") or []}
        observed=[]
        for proposal in freeze["proposals"]:
            width=int(proposal["width"]);fr=one_freeze(proposal);decision={"freeze":fr}
            pos=paper_position(fr,0)
            unwind=_unwind(rpc,pool,decision,{"terminal_state":terminal},end)
            outcome=paper_outcome(pos,terminal,unwind=unwind,costs={},lp_fees_captured=None)
            employed=int(proposal["capital_employed"])
            row=dict(
                width=width,capital_quote_raw=employed,
                inventory_effect=outcome.get("inventory_effect"),
                executable_slippage=outcome.get("executable_slippage"),
                gross_result=outcome.get("gross_result"),
                gross_return_bps=(None if outcome.get("gross_result") is None or employed<=0
                                  else int(outcome["gross_result"])*10000//employed),
                unresolved_inventory=outcome.get("unresolved_inventory"),
            )
            observed.append(row)
            exp=expected.get(width)
            if exp is None:
                mismatches.append(dict(pool=pool,width=width,field="variant_missing"))
                continue
            for field in ("capital_quote_raw","inventory_effect","executable_slippage",
                          "gross_result","gross_return_bps","unresolved_inventory"):
                if row.get(field)!=exp.get(field):
                    mismatches.append(dict(
                        pool=pool,width=width,field=field,
                        expected=exp.get(field),observed=row.get(field),
                    ))
        results.append(dict(
            pool=pool,entry_block=entry,end_block=end,
            terminal_active=terminal["active"],observed=observed,
        ))
    body=dict(
        kind="ramses_terminal_state_equivalence_v1",
        research_only=True,
        source_run=35662680789,
        variants_checked=sum(len(r["observed"]) for r in results),
        candidates_checked=len(results),
        mismatches=mismatches,
        exact_equivalence=(not mismatches),
        fields_checked=[
            "capital_quote_raw","inventory_effect","executable_slippage",
            "gross_result","gross_return_bps","unresolved_inventory",
        ],
        note=("LP fee decomposition is not reproduced here because gross P&L in the existing "
              "paper model is already embedded in exact terminal bin reserves. The fields "
              "used by the frozen Branch A/B evaluator are compared bit-for-bit."),
        results=results,provider=rpc.telemetry(),
    )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps({
        "status":"complete","exact_equivalence":body["exact_equivalence"],
        "variants_checked":body["variants_checked"],"mismatches":len(mismatches),
    },sort_keys=True))
    if mismatches:
        raise RuntimeError("terminal_state_equivalence_failed")

if __name__=="__main__": main()
