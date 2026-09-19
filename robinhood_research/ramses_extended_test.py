"""Extended live Ramses Fee Pulse market test.

Natural phase:
- repeatedly scan the complete authenticated Ramses factory;
- never change the frozen strategy policy;
- preserve every screen and rejection;
- if a genuine qualifier appears, hand that exact frozen screen into the
  connected independent lifecycle.

Machinery phase (only when natural phase has no qualifier):
- choose the highest-ranked real Ramses pool with a valid frozen proposal;
- explicitly mark the run forced/mechanics-only and strategy-ineligible;
- reserve/open in the independent ledger;
- observe real finalized market state for 60 seconds;
- exact replay -> same-pool unwind -> settlement -> reconciliation.

The forced phase is operational proof only and cannot be used as alpha or
profitability evidence.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import time

from . import BoundaryError
from .ramses_all_pool_lifecycle import (
    _canonicalize_selected_row,
    compact_lifecycle_result,
    _build_segment_replay,
    _position_state_from_prestate,
    _unwind,
    run as run_connected,
    select_qualifier,
)
from .ramses_capture import BoundedMultiRpc, _first_finalized_block_at_or_after
from .ramses_strategy import (
    POLICY_HASH,
    STRATEGY_DOMAIN,
    STRATEGY_VERSION,
    decompose_pnl,
)
from .ramses import verify_proposal_hash
from .ramses_strategy_ledger import RamsesStrategyLedger
from .ramses_universe import scan

REPORT = Path(os.environ.get(
    "MM_ROBINHOOD_RAMSES_EXTENDED_REPORT",
    "robinhood-ramses-extended-market-report.json",
))
DB = Path(os.environ.get(
    "MM_ROBINHOOD_RAMSES_EXTENDED_DB",
    "robinhood-ramses-extended-market.sqlite",
))

DISCOVERY_SECONDS = 600
DISCOVERY_INTERVAL_SECONDS = 60
FORCED_FORWARD_SECONDS = 60
FORCED_PROVIDER_COOLDOWN_SECONDS = 8
FORCED_BATCH_SIZE = 6
FORCED_BATCH_PAUSE_SECONDS = 1.0
FORCED_RATE_COOLDOWN_SECONDS = 8.0


def _json_env(name):
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        raise BoundaryError("invalid_" + name.lower()) from None
    if not isinstance(value, dict):
        raise BoundaryError("invalid_" + name.lower())
    return {str(k).lower(): v for k, v in value.items()}


def _screen_summary(screen):
    rows=[]
    for row in screen.get("rows",[]):
        d=row.get("decision") or {}
        f=row.get("features") or {}
        rows.append(dict(
            pool=row.get("pool"),
            swaps=row.get("swap_count"),
            turnover_bps=f.get("turnover_bps"),
            turnover_percentile_bps=f.get("turnover_percentile_bps"),
            fee_percentile_bps=f.get("fee_percentile_bps"),
            volume_acceleration_milli=f.get("volume_acceleration_milli"),
            chop_ratio_milli=f.get("chop_ratio_milli"),
            flow_imbalance_bps=f.get("flow_imbalance_bps"),
            mode=d.get("mode"),
            qualified=d.get("qualified"),
            reasons=d.get("reasons"),
            gas_costs=row.get("gas_costs"),
            cost_evidence=row.get("cost_evidence"),
        ))
    return dict(
        finalized_block=screen.get("finalized_block"),
        finalized_timestamp=screen.get("finalized_timestamp"),
        factory_pool_count=screen.get("factory_pool_count"),
        factory_inventory_cache=screen.get("factory_inventory_cache"),
        pools_with_recent_swaps=screen.get("pools_with_recent_swaps"),
        state_complete_pools=screen.get("state_complete_pools"),
        qualified=[
            r["pool"] for r in screen.get("rows",[])
            if (r.get("decision") or {}).get("qualified")
        ],
        rows=rows,
        cost_model=screen.get("cost_model"),
        pools_with_automatic_cost_evidence=screen.get(
            "pools_with_automatic_cost_evidence"
        ),
        provider=screen.get("provider"),
    )


def _pick_forced_row(screens):
    for screen in reversed(screens):
        for row in screen.get("rows",[]):
            decision=row.get("decision") or {}
            freeze=decision.get("freeze")
            if freeze and freeze.get("proposals"):
                verify_proposal_hash(freeze)
                return screen,row
    return None,None


def _exact_forced_horizon(rpc, entry_block, entry_at, finalized_frontier):
    """Select the earliest finalized block at or after the frozen +60s target."""
    target = int(entry_at) + FORCED_FORWARD_SECONDS
    selected, previous, reads = _first_finalized_block_at_or_after(
        rpc, int(entry_block), finalized_frontier, target
    )
    end_block = int(selected["number"], 16)
    end_at = int(selected["timestamp"], 16)
    previous_block = int(previous["number"], 16)
    previous_at = int(previous["timestamp"], 16)
    if (
        end_at < target
        or previous_at >= target
        or end_block <= int(entry_block)
        or previous_block != end_block - 1
    ):
        raise BoundaryError("extended_forced_exact_horizon_disagreement")
    return selected, dict(
        target_timestamp=target,
        selected_block=end_block,
        selected_timestamp=end_at,
        previous_block=previous_block,
        previous_timestamp=previous_at,
        selected_elapsed_seconds=end_at-int(entry_at),
        previous_elapsed_seconds=previous_at-int(entry_at),
        binary_search_reads=reads,
        earliest_finalized_at_or_after_target=True,
    )


def _forced_machinery(endpoint, screen, row, *, db_path):
    pool=row["pool"].lower()
    entry_block=int(screen["finalized_block"])
    entry_at=int(screen["finalized_timestamp"])

    rpc=BoundedMultiRpc(
        endpoint,
        max_sessions=12,
        batch_size=FORCED_BATCH_SIZE,
        batch_pause=FORCED_BATCH_PAUSE_SECONDS,
        rate_retries=3,
        rate_cooldown=FORCED_RATE_COOLDOWN_SECONDS,
        adaptive_batch_floor=2,
    )
    rpc.verify_chain()
    canonical_row,auth=_canonicalize_selected_row(
        rpc,row,screen,costs_by_pool={},signals_by_pool={}
    )
    row=canonical_row
    decision=deepcopy(row["decision"])
    if not decision.get("freeze") or not decision["freeze"].get("proposals"):
        raise BoundaryError("extended_forced_canonical_proposal_unavailable")
    decision["forced_machinery_test"]=True
    decision["strategy_evidence_eligible"]=False
    verify_proposal_hash(decision["freeze"])
    capital=int(decision["freeze"]["proposals"][0]["capital_employed"])
    if capital<=0:
        raise BoundaryError("extended_forced_capital")

    path=Path(db_path)
    if path.exists():
        raise BoundaryError("extended_forced_db_already_exists")
    ledger=RamsesStrategyLedger(
        str(path),paper_capital=capital,quote_asset=row["token_y"]
    )
    identity=(
        "forced-connected:"+pool+":"+str(entry_block)+":"
        +decision["freeze"]["proposal_hash"]
    )
    result=dict(
        authority="forced_connected_machinery_test",
        paper_only=True,
        natural_proof=False,
        strategy_evidence_eligible=False,
        allocation_authority=False,
        pool=pool,
        proposal_hash=decision["freeze"]["proposal_hash"],
        qualifier_authentication=auth,
        entry_block=entry_block,
        entry_at=entry_at,
    )
    try:
        result["reserved"]=ledger.reserve_forced_machinery(
            identity,pool=pool,decision=decision,at=entry_at
        )
        result["opened"]=ledger.open(identity,at=entry_at)
        before=ledger.reconcile()
        ledger.close()
        ledger=RamsesStrategyLedger(
            str(path),paper_capital=capital,quote_asset=row["token_y"]
        )
        after=ledger.reconcile()
        if before!=after or ledger.position(identity)["status"]!="open":
            raise BoundaryError("extended_forced_restart_reconciliation")
        result["entry_restart_proven"]=True

        state_now=_position_state_from_prestate(row["prestate"],decision)
        ledger.checkpoint(
            identity,
            action="monitor",
            detail=dict(
                forced_machinery_test=True,
                block=entry_block,
                active_bin=state_now["active"],
                inventory_value=state_now["inventory_value"],
                action=dict(action="hold",reason="forced_machinery_horizon"),
            ),
            at=entry_at,
        )

        target=entry_at+FORCED_FORWARD_SECONDS
        deadline=time.monotonic()+300
        frontier=rpc.call(
            "eth_getBlockByNumber",["finalized",False],scope="extended_forward"
        )
        while int(frontier["timestamp"],16)<target:
            if time.monotonic()>=deadline:
                raise BoundaryError("extended_forced_finality_timeout")
            time.sleep(10)
            frontier=rpc.call(
                "eth_getBlockByNumber",["finalized",False],scope="extended_forward"
            )
        selected,horizon=_exact_forced_horizon(
            rpc,entry_block,entry_at,frontier
        )
        end_block=int(selected["number"],16)
        end_at=int(selected["timestamp"],16)
        result["horizon"]=horizon
        capture,replay_result=_build_segment_replay(
            rpc,pool,decision,entry_block,end_block
        )
        unwind=_unwind(rpc,pool,decision,replay_result,end_block)
        costs={"mechanics_only_placeholder":0}
        pnl=decompose_pnl(
            decision,replay_result,unwind=unwind,costs=costs
        )
        pnl["forced_machinery_test"]=True
        pnl["strategy_evidence_eligible"]=False
        pnl["economic_cost_evidence"]=False
        ledger.checkpoint(
            identity,
            action="segment_close",
            detail=dict(
                forced_machinery_test=True,
                end_block=end_block,
                terminal_equality=replay_result["terminal_equality"],
                net_result_quote=pnl.get("net_result_quote"),
            ),
            at=end_at,
        )
        result["segment"]=dict(
            start_block=entry_block,
            end_block=end_block,
            seconds=end_at-entry_at,
            events=replay_result["events"],
            transactions=replay_result["transactions"],
            terminal_equality=replay_result["terminal_equality"],
            unwind=unwind,
            pnl=pnl,
        )
        result["final_position"]=ledger.settle(
            identity,pnl=pnl,at=end_at
        )
        pre_restart=ledger.reconcile()
        ledger.close()
        ledger=RamsesStrategyLedger(
            str(path),paper_capital=capital,quote_asset=row["token_y"]
        )
        post_restart=ledger.reconcile()
        if pre_restart!=post_restart:
            raise BoundaryError("extended_forced_final_restart_reconciliation")
        result["final_restart_proven"]=True
        result["reconciliation"]=post_restart
        result["mechanics_complete"]=(
            ledger.position(identity)["status"]=="settled"
            and replay_result["terminal_equality"] is True
            and post_restart["open_positions"]==0
        )
    finally:
        try:
            ledger.close()
        except Exception:
            pass
    result["provider"]=rpc.telemetry()
    return result


def run(
    endpoint,
    *,
    costs_by_pool=None,
    signals_by_pool=None,
    discovery_seconds=DISCOVERY_SECONDS,
    discovery_interval_seconds=DISCOVERY_INTERVAL_SECONDS,
    db_path=None,
):
    if type(discovery_seconds) not in (int,float) or not 60<=discovery_seconds<=1800:
        raise BoundaryError("extended_discovery_seconds")
    if type(discovery_interval_seconds) not in (int,float) or not 20<=discovery_interval_seconds<=300:
        raise BoundaryError("extended_discovery_interval")
    costs_by_pool=costs_by_pool or {}
    signals_by_pool=signals_by_pool or {}
    started=time.monotonic()
    screens=[]
    seen_pools=set()
    cost_state={}
    result=dict(
        kind="ramses_fee_pulse_extended_market_test_v1",
        strategy_domain=STRATEGY_DOMAIN,
        strategy_version=STRATEGY_VERSION,
        policy_hash=POLICY_HASH,
        paper_only=True,
        allocation_authority=False,
        thresholds_changed=False,
        natural_discovery_seconds=discovery_seconds,
        discovery_interval_seconds=discovery_interval_seconds,
        started_at=time.time(),
        natural_screens=[],
    )

    while True:
        screen=scan(
            endpoint,
            gas_costs_by_pool=costs_by_pool,
            signals_by_pool=signals_by_pool,
            cost_state=cost_state,
        )
        screens.append(screen)
        for row in screen.get("rows",[]):
            seen_pools.add(row["pool"])
        summary=_screen_summary(screen)
        summary["elapsed_seconds"]=time.monotonic()-started
        result["natural_screens"].append(summary)
        chosen=select_qualifier(screen)
        if chosen is not None:
            result["natural_qualifier_found"]=True
            result["natural_qualifier_pool"]=chosen["pool"]
            result["connected_lifecycle"]=run_connected(
                endpoint,
                costs_by_pool=costs_by_pool,
                signals_by_pool=signals_by_pool,
                db_path=str(db_path or DB),
                initial_screen=screen,
                cost_state=cost_state,
            )
            result["status"]=result["connected_lifecycle"].get("status")
            result["ended_at"]=time.time()
            result["unique_active_pools"]=len(seen_pools)
            result["cost_state_summary"]=dict(
                transactions_observed=len(cost_state.get("transactions") or {}),
                sample_counts={
                    k: len(v)
                    for k,v in (cost_state.get("samples") or {}).items()
                },
            )
            return result

        elapsed=time.monotonic()-started
        if elapsed>=discovery_seconds:
            break
        sleep_for=min(
            discovery_interval_seconds,
            max(0,discovery_seconds-elapsed),
        )
        if sleep_for:
            time.sleep(sleep_for)

    result["natural_qualifier_found"]=False
    result["unique_active_pools"]=len(seen_pools)
    result["cost_state_summary"]=dict(
        transactions_observed=len(cost_state.get("transactions") or {}),
        sample_counts={
            k: len(v)
            for k,v in (cost_state.get("samples") or {}).items()
        },
    )
    result["status"]="natural_discovery_complete_no_qualifier"
    screen,row=_pick_forced_row(screens)
    if row is None:
        result["forced_machinery"]=dict(
            mechanics_complete=False,
            boundary="no_active_ramses_pool_for_machinery_proof",
        )
    else:
        try:
            if FORCED_PROVIDER_COOLDOWN_SECONDS:
                time.sleep(FORCED_PROVIDER_COOLDOWN_SECONDS)
            result["forced_machinery"]=_forced_machinery(
                endpoint,screen,row,db_path=str(db_path or DB)
            )
        except BoundaryError as exc:
            result["forced_machinery"]=dict(
                mechanics_complete=False,
                boundary=str(exc),
                paper_only=True,
                strategy_evidence_eligible=False,
            )
    result["ended_at"]=time.time()
    return result


def main():
    costs=_json_env("MM_ROBINHOOD_RAMSES_COSTS_BY_POOL_JSON")
    signals=_json_env("MM_ROBINHOOD_RAMSES_SIGNALS_BY_POOL_JSON")
    result=run(
        os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""),
        costs_by_pool=costs,
        signals_by_pool=signals,
        discovery_seconds=float(os.environ.get(
            "MM_ROBINHOOD_RAMSES_EXTENDED_DISCOVERY_SECONDS",
            DISCOVERY_SECONDS,
        )),
        discovery_interval_seconds=float(os.environ.get(
            "MM_ROBINHOOD_RAMSES_EXTENDED_INTERVAL_SECONDS",
            DISCOVERY_INTERVAL_SECONDS,
        )),
        db_path=str(DB),
    )
    public_result=deepcopy(result)
    if isinstance(public_result.get("connected_lifecycle"),dict):
        public_result["connected_lifecycle"]=compact_lifecycle_result(
            public_result["connected_lifecycle"]
        )
    raw=json.dumps(public_result,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>12_000_000:
        raise BoundaryError("extended_market_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        status=result.get("status"),
        screens=len(result.get("natural_screens") or []),
        unique_active_pools=result.get("unique_active_pools"),
        natural_qualifier_found=result.get("natural_qualifier_found"),
        natural_qualifier_pool=result.get("natural_qualifier_pool"),
        connected_status=(result.get("connected_lifecycle") or {}).get("status"),
        forced_mechanics_complete=(result.get("forced_machinery") or {}).get("mechanics_complete"),
        forced_pool=(result.get("forced_machinery") or {}).get("pool"),
        forced_final_status=((result.get("forced_machinery") or {}).get("final_position") or {}).get("status"),
    )))


if __name__=="__main__":
    main()
