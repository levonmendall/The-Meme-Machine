"""One bounded prospective Ramses strategy classification/evaluation sample."""
import base64
import json
import os
from pathlib import Path
import time
import zlib

from . import BoundaryError
from .abi import calldata
from .provider_topology import configured_dlmm_rpc
from .ramses import paper_position, paper_removal, price, quote_value, values
from .ramses_capture import PAPER_NATIVE_CAPITAL, run
from .ramses_strategy import STRATEGY_DOMAIN, classify_pool, decompose_pnl
from .ramses_strategy_ledger import RamsesStrategyLedger

REPORT = Path(os.environ.get("MM_ROBINHOOD_RAMSES_STRATEGY_REPORT", "robinhood-ramses-strategy-report.json"))
DB = Path(os.environ.get("MM_ROBINHOOD_RAMSES_STRATEGY_DB", "robinhood-ramses-strategy.sqlite"))


def _json_env(name):
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        raise BoundaryError("invalid_" + name.lower()) from None
    return value


def _terminal_unwind(endpoint, capture, decision):
    position = paper_position(decision["freeze"], 0)
    terminal = capture["replay"]["terminal_state"]
    removal = paper_removal(position, terminal)["amounts"]
    quote_side = position["quote_side"]
    nonquote = 0 if quote_side == "y" else 1
    amount = removal[nonquote]
    if not amount:
        return None, None
    if amount >= 2**128:
        raise BoundaryError("strategy_unwind_amount_capacity")
    rpc = configured_dlmm_rpc(endpoint, limit=20, per_scope=20, retries=0)
    end = int(capture["frontier"]["number"], 16)
    for_y = 1 if quote_side == "y" else 0
    raw = rpc.call(
        "eth_call",
        [dict(to=capture["pool"], data=calldata("getSwapOut(uint128,bool)", amount, for_y)), hex(end)],
        scope="strategy_unwind",
    )
    q = values(raw)
    spot = price(terminal["active"], terminal["step"])
    expected = quote_value([amount, 0] if nonquote == 0 else [0, amount], spot, quote_side)
    unwind = {
        "input_side": "x" if nonquote == 0 else "y",
        "amount_in": amount,
        "amount_in_left": q[0],
        "amount_out": q[1],
        "fee": q[2],
        "slippage": max(0, expected - q[1]),
        "block": end,
    }
    return unwind, rpc.telemetry()


def main():
    endpoint = os.environ.get("MM_ROBINHOOD_READ_RPC_URL", "")
    result = {
        "kind": "ramses_strategy_prospective_sample_v1",
        "started_at": time.time(),
        "paper_only": True,
        "allocation_authority": False,
        "shared_allocator": False,
        "strategy_domain": STRATEGY_DOMAIN,
    }
    capture = run(endpoint)
    result["capture"] = capture
    if not capture.get("replay") or not capture.get("range_freeze"):
        result["boundary"] = capture.get("boundary") or "strategy_preentry_capture_unavailable"
    else:
        costs = _json_env("MM_ROBINHOOD_RAMSES_COSTS_JSON")
        universe = _json_env("MM_ROBINHOOD_RAMSES_UNIVERSE_FEATURES_JSON")
        anchor = _json_env("MM_ROBINHOOD_RAMSES_ANCHOR_SIGNAL_JSON")
        directional = _json_env("MM_ROBINHOOD_RAMSES_DIRECTIONAL_SIGNAL_JSON")
        prestate = capture["replay"]["initial_state"]
        entry_timestamp = capture["range_freeze"]["pre_entry_time"]
        decision = classify_pool(
            prestate, capture.get("prehistory", []), capture["quote_side"],
            requested_capital=PAPER_NATIVE_CAPITAL,
            entry_timestamp=entry_timestamp,
            gas_costs=costs,
            universe_features=universe,
            anchor_signal=anchor,
            directional_signal=directional,
            now=entry_timestamp,
            pool=capture.get("pool"),
        )
        result["decision"] = decision
        if decision["qualified"]:
            proposal_capital = decision["freeze"]["proposals"][0]["capital_employed"]
            if DB.exists():
                raise BoundaryError("ramses_strategy_db_already_exists")
            ledger = RamsesStrategyLedger(
                str(DB),
                paper_capital=max(PAPER_NATIVE_CAPITAL, proposal_capital),
                quote_asset=capture.get("quote_asset") or "unknown",
            )
            identity = (
                STRATEGY_DOMAIN + ":" + str(capture["pool"]).lower() + ":"
                + str(capture["range_freeze"]["pre_entry_block"]) + ":"
                + decision["freeze"]["proposal_hash"]
            )
            try:
                result["strategy_ledger_reserve"] = ledger.reserve(
                    identity,
                    pool=capture["pool"],
                    decision=decision,
                    at=entry_timestamp,
                )
                result["strategy_ledger_open"] = ledger.open(identity, at=entry_timestamp)
                unwind, telemetry = _terminal_unwind(endpoint, capture, decision)
                result["strategy_provider"] = telemetry
                result["pnl"] = decompose_pnl(
                    decision, capture["replay"], unwind=unwind, costs=costs
                )
                terminal_at = int(capture["frontier"]["timestamp"], 16)
                result["strategy_ledger_final"] = ledger.settle(
                    identity, pnl=result["pnl"], at=terminal_at
                )
                result["strategy_ledger_reconciliation"] = ledger.reconcile()
            finally:
                ledger.close()
        else:
            result["pnl"] = None
        result["boundary"] = None
    result["ended_at"] = time.time()
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > 2_000_000:
        raise BoundaryError("ramses_strategy_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps({
        "boundary": result.get("boundary"),
        "capture_boundary": capture.get("boundary"),
        "pool": capture.get("pool"),
        "mode": (result.get("decision") or {}).get("mode"),
        "qualified": (result.get("decision") or {}).get("qualified"),
        "policy_hash": (result.get("decision") or {}).get("policy_hash"),
    }))
    data = base64.b64encode(zlib.compress(raw, 9)).decode()
    for i in range(0, len(data), 6000):
        print("PUBLIC_EVIDENCE_CHUNK " + str(i // 6000) + " " + data[i:i + 6000])


if __name__ == "__main__":
    main()
