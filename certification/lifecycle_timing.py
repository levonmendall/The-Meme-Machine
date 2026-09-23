"""Operational lifecycle timing repairs for four-lane certification.

No strategy threshold, market scope, sizing, finality, cost model, or paper-only
authority lives here.  This module only separates a bounded market-observation
window from longer paper-position lifecycles and preserves restartable state.
"""
from __future__ import annotations

from copy import deepcopy
import atexit
import json
import os
from pathlib import Path
import threading
import time

METEORA_TRIGGER_SECONDS = 120
METEORA_WARMUP_SECONDS = 12
METEORA_EVIDENCE_RESERVE_SECONDS = 30
METEORA_PREENTRY_RESERVE_SECONDS = (
    METEORA_TRIGGER_SECONDS + METEORA_WARMUP_SECONDS + METEORA_EVIDENCE_RESERVE_SECONDS
)
RAMSES_RECENTER_TARGET_SECONDS = 180
RAMSES_RECENTER_DEADLINE_SECONDS = 210
RAMSES_MAX_HOLD_SECONDS = 604800

_RAMSES_LOCK = threading.RLock()
_RAMSES_STATE = {
    "active": False,
    "thread": None,
    "proxy": None,
    "ledger_path": None,
    "paper_capital": None,
    "quote_asset": None,
    "state_path": "robinhood-ramses-continuation.json",
    "observations_while_occupied": 0,
    "result": None,
    "error": None,
}
_RAMSES_TLS = threading.local()


def ramses_max_hold_reached(elapsed_seconds, max_holding_seconds=RAMSES_MAX_HOLD_SECONDS):
    return int(elapsed_seconds) >= int(max_holding_seconds)


def ramses_recenter_clock(elapsed_seconds):
    elapsed=float(elapsed_seconds)
    if elapsed > RAMSES_RECENTER_DEADLINE_SECONDS:
        return "hard_deadline"
    if elapsed > RAMSES_RECENTER_TARGET_SECONDS:
        return "target_miss"
    return "within_target"


def _atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def _hourly():
    return os.environ.get("MM_CERTIFICATION_PHASE") == "hourly"


def meteora_preentry_remaining_ok(deadline, *, clock=None):
    """Admission is operationally serviceable only if the whole entry sequence fits."""
    if deadline is None:
        return True
    clock = time.monotonic if clock is None else clock
    return float(deadline) - float(clock()) >= METEORA_PREENTRY_RESERVE_SECONDS


def install_meteora(module):
    """Install hourly-only pre-entry cutoff and asynchronous durable lifecycle ownership."""
    if getattr(module, "_cert_lifecycle_timing_installed", False):
        return
    module._cert_lifecycle_timing_installed = True
    module._cert_continuation_results = []
    module._cert_continuation_lock = threading.RLock()
    original_checkpoint = getattr(module,"_atomic_checkpoint",None)
    if original_checkpoint is not None:
        def continuation_checkpoint(report,stage,*args,**kwargs):
            with module._cert_continuation_lock:
                report["continuation_lifecycles"] = deepcopy(
                    module._cert_continuation_results
                )
            return original_checkpoint(report,stage,*args,**kwargs)
        module._atomic_checkpoint = continuation_checkpoint

    original_trigger = module._triggered_warmup

    def triggered_warmup(
        adapter, candidate, compatibility_state, policy, pacer, rpcs,
        deadline=None, broker=None
    ):
        if _hourly() and not meteora_preentry_remaining_ok(deadline):
            remaining = None if deadline is None else max(0.0, float(deadline)-time.monotonic())
            return (
                dict(
                    aligned=False,
                    reason="campaign_window_insufficient_preentry_time",
                    trigger=None,
                    admission_capacity=True,
                    economic_rejection=False,
                    required_remaining_seconds=METEORA_PREENTRY_RESERVE_SECONDS,
                    remaining_seconds=remaining,
                ),
                None, None, None, adapter, candidate,
            )
        return original_trigger(
            adapter, candidate, compatibility_state, policy, pacer, rpcs,
            deadline, broker
        )

    module._triggered_warmup = triggered_warmup
    original_lifecycle = module._lifecycle

    def lifecycle(adapter, address, entry, features, policy, pacer, rpcs,
                  deadline=None, broker=None, book=None):
        if not _hourly() or book is None:
            return original_lifecycle(
                adapter, address, entry, features, policy, pacer, rpcs,
                deadline, broker, book
            )

        proxy = dict(
            complete=False,
            lifecycle_id=None,
            reason="durable_position_continuation_active",
            handoff_required=True,
            paper_only=True,
            economic_rejection=False,
        )
        state_path = Path("solana-dlmm-independent-v1-live.continuation.json")

        def snapshot(status, **extra):
            row = dict(
                schema="meteora-position-continuation-v1",
                lane="meteora",
                status=status,
                policy_hash=module.digest(policy),
                pool=address,
                entry_slot=entry.get("slot"),
                entry_time=entry.get("time"),
                maximum_holding_seconds=int(policy["range"]["max_holding_seconds"]),
                accounting_path=str(book.path),
                accounting=book.reconcile(),
                updated_at=time.time(),
                **extra,
            )
            _atomic_json(state_path, row)

        # The lifecycle gets independent provider objects.  Shared physical transport
        # limits are still enforced by the certification transport wrapper/governor.
        def target():
            life_broker = None
            try:
                life_pacer = module.provider.AlchemyPacer()
                life_rpcs = []
                module._prove_network_identity(life_pacer, life_rpcs)
                life_adapter = module._new_adapter(life_pacer, life_rpcs)
                life_broker = module.EvidenceBroker(module.DLMM_BROKER_DB)
                maximum = int(policy["range"]["max_holding_seconds"])
                life_deadline = time.monotonic() + maximum + 300
                snapshot("active")
                result, _ = original_lifecycle(
                    life_adapter, address, entry, features, policy,
                    life_pacer, life_rpcs, life_deadline, life_broker, book
                )
                proxy.clear()
                proxy.update(result)
                proxy["handoff_required"] = not bool(result.get("complete"))
                proxy["continuation_completed"] = bool(result.get("complete"))
                with module._cert_continuation_lock:
                    module._cert_continuation_results.append(deepcopy(result))
                snapshot(
                    "settled" if result.get("complete") else "handoff_required",
                    lifecycle=result,
                )
            except BaseException as exc:
                proxy.update(
                    complete=False,
                    handoff_required=True,
                    continuation_error_type=type(exc).__name__,
                    continuation_error=str(exc)[:200],
                )
                try:
                    snapshot(
                        "handoff_required",
                        error_type=type(exc).__name__,
                        error=str(exc)[:200],
                    )
                except Exception:
                    pass
            finally:
                if life_broker is not None:
                    try:
                        life_broker.close()
                    except Exception:
                        pass

        thread = threading.Thread(
            target=target,
            name="meteora-position-continuation",
            daemon=True,
        )
        thread.start()
        # The native PaperBook reservation/entry is performed inside target before
        # the next candidate can pass the hourly occupied-capital gate.
        for _ in range(200):
            accounting = book.reconcile()
            if accounting.get("unsettled"):
                proxy["lifecycle_id"] = next(
                    (
                        identity for identity in _open_meteora_identities(book.path)
                    ),
                    None,
                )
                break
            if not thread.is_alive():
                break
            time.sleep(0.01)
        snapshot("active" if thread.is_alive() else "terminal")
        return proxy, adapter

    module._lifecycle = lifecycle


def _open_meteora_identities(path):
    import sqlite3
    rows = {}
    with sqlite3.connect(path) as db:
        for (raw,) in db.execute("SELECT body FROM events ORDER BY seq"):
            event = json.loads(raw)
            identity = event.get("identity")
            if identity:
                rows[identity] = event.get("action")
    return [identity for identity, action in rows.items()
            if action not in ("cancel", "settle", "writeoff")]


def _ramses_write_state():
    with _RAMSES_LOCK:
        path = Path(_RAMSES_STATE["state_path"])
        row = {
            key: value for key, value in _RAMSES_STATE.items()
            if key not in ("thread", "proxy")
        }
        row["schema"] = "ramses-position-continuation-v1"
        row["updated_at"] = time.time()
        try:
            _atomic_json(path, row)
        except TypeError:
            # State is expected to be JSON-native.  Fail closed to a minimal receipt
            # rather than suppressing the durable ledger.
            _atomic_json(path, dict(
                schema="ramses-position-continuation-v1",
                active=bool(_RAMSES_STATE.get("active")),
                ledger_path=_RAMSES_STATE.get("ledger_path"),
                error="continuation_state_not_json_serializable",
                updated_at=time.time(),
            ))


def _ramses_snapshot_accounting():
    with _RAMSES_LOCK:
        path = _RAMSES_STATE.get("ledger_path")
        capital = _RAMSES_STATE.get("paper_capital")
        asset = _RAMSES_STATE.get("quote_asset")
    if not path or not capital or not asset or not Path(path).exists():
        return None
    from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger
    book = RamsesStrategyLedger(path, paper_capital=int(capital), quote_asset=asset)
    try:
        return book.reconcile()
    finally:
        book.close()


def install_ramses(extended_module):
    """Decouple Ramses discovery from one active long-horizon position."""
    if getattr(extended_module, "_cert_lifecycle_timing_installed", False):
        return
    extended_module._cert_lifecycle_timing_installed = True

    from robinhood_research import ramses_all_pool_lifecycle as lifecycle
    from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger

    original_controller = lifecycle.controller_action
    original_requalify = lifecycle._requalify_current_pool
    original_decompose = lifecycle.decompose_pnl
    original_checkpoint = RamsesStrategyLedger.checkpoint
    original_reserve = RamsesStrategyLedger.reserve

    def controller(decision, **kwargs):
        elapsed = int(kwargs.get("elapsed_seconds") or 0)
        if ramses_max_hold_reached(
            elapsed,
            lifecycle.POLICY["controller"].get(
                "max_holding_seconds", RAMSES_MAX_HOLD_SECONDS
            ),
        ):
            return {
                "action": "exit",
                "reason": "maximum_holding_time",
                "elapsed_seconds": elapsed,
            }
        action = original_controller(decision, **kwargs)
        if action.get("action") == "rebalance":
            _RAMSES_TLS.recenter_started = time.monotonic()
            _RAMSES_TLS.recenter_mode = action.get("mode") or "recenter"
        return action

    def requalify(*args, **kwargs):
        started = getattr(_RAMSES_TLS, "recenter_started", None)
        if started is not None and ramses_recenter_clock(
            time.monotonic()-started
        )=="hard_deadline":
            manager = getattr(_RAMSES_TLS, "manager", None)
            if manager is not None:
                manager.setdefault("recenter_deadline_misses", []).append(dict(
                    at=time.time(),
                    elapsed_seconds=time.monotonic()-started,
                    action="discard_stale_geometry_and_redecide_from_fresh_scan",
                ))
            # The caller has just obtained a fresh finalized screen.  Reset the
            # same-decision clock and treat this as a new decision, never a stale remint.
            _RAMSES_TLS.recenter_started = time.monotonic()
            _RAMSES_TLS.recenter_redecision = True
        value = original_requalify(*args, **kwargs)
        manager = getattr(_RAMSES_TLS, "manager", None)
        if manager is not None and isinstance(value, dict):
            manager["pending_rebalance"] = dict(
                old_decision=deepcopy(manager.get("decision")),
                new_decision=deepcopy(value),
                new_proposal_hash=(value.get("freeze") or {}).get("proposal_hash"),
                prepared_at=time.time(),
            )
            _ramses_write_state()
        return value

    def decompose(*args, **kwargs):
        value = original_decompose(*args, **kwargs)
        _RAMSES_TLS.last_pnl = deepcopy(value)
        return value

    def reserve(self, identity, *, pool, decision, at):
        value = original_reserve(self, identity, pool=pool, decision=decision, at=at)
        manager = getattr(_RAMSES_TLS, "manager", None)
        if manager is not None:
            row=next(
                (x for x in (getattr(_RAMSES_TLS,"initial_screen",{}) or {}).get("rows",[])
                 if str(x.get("pool","")).lower()==str(pool).lower()),
                None,
            )
            explicit=(getattr(_RAMSES_TLS,"costs_by_pool",{}) or {}).get(str(pool).lower())
            manager.update(
                lifecycle_id=identity,
                pool=pool,
                decision=deepcopy(decision),
                costs=deepcopy((row or {}).get("gas_costs") or explicit),
                entry_at=int(at),
                segment_start=int(manager.get("entry_block") or 0),
                current_capital=int(decision["freeze"]["proposals"][0]["capital_employed"]),
                position_phase="deployed",
            )
            _ramses_write_state()
        return value

    def checkpoint(self, identity, *, action, detail, at):
        if action == "rebalance":
            started = getattr(_RAMSES_TLS, "recenter_started", None)
            if started is not None:
                elapsed = time.monotonic()-started
                clock_state=ramses_recenter_clock(elapsed)
                if clock_state=="hard_deadline":
                    raise lifecycle.BoundaryError("ramses_recenter_decision_deadline")
                manager = getattr(_RAMSES_TLS, "manager", None)
                if manager is not None and clock_state=="target_miss":
                    manager.setdefault("recenter_target_misses", []).append(dict(
                        at=time.time(), elapsed_seconds=elapsed,
                    ))
        value = original_checkpoint(self, identity, action=action, detail=detail, at=at)
        manager = getattr(_RAMSES_TLS, "manager", None)
        if manager is not None:
            manager["last_checkpoint"] = dict(action=action, detail=deepcopy(detail), at=int(at))
            if action == "segment_close":
                manager.setdefault("segments", []).append(dict(
                    index=len(manager.get("segments",[])),
                    initial_cost_basis=int(
                        manager.get("decision",{}).get("freeze",{}).get("proposals",[{}])[0].get(
                            "capital_employed", manager.get("current_capital") or 0
                        )
                    ),
                    detail=deepcopy(detail),
                    pnl=deepcopy(getattr(_RAMSES_TLS, "last_pnl", None)),
                ))
                manager["position_phase"] = "flat_quote"
            elif action == "rebalance":
                pending=manager.get("pending_rebalance") or {}
                proposal_hash=detail.get("proposal_hash")
                if pending.get("new_proposal_hash")!=proposal_hash:
                    raise lifecycle.BoundaryError("ramses_recenter_pending_decision_mismatch")
                manager["decision"] = deepcopy(pending["new_decision"])
                manager.pop("pending_rebalance",None)
                manager["segment_start"] = int(detail.get("block") or manager.get("segment_start") or 0)
                manager["rebalances"] = int(manager.get("rebalances", 0))+1
                manager["current_capital"] = int(detail.get("capital") or manager.get("current_capital") or 0)
                manager["position_phase"] = "deployed"
                _RAMSES_TLS.recenter_started = None
            _ramses_write_state()
        return value

    lifecycle.controller_action = controller
    lifecycle._requalify_current_pool = requalify
    lifecycle.decompose_pnl = decompose
    RamsesStrategyLedger.reserve = reserve
    RamsesStrategyLedger.checkpoint = checkpoint

    original_run_connected = extended_module.run_connected
    original_select = extended_module.select_qualifier
    original_persist = extended_module._persist_public_result

    def select_qualifier(screen):
        if _hourly():
            with _RAMSES_LOCK:
                if _RAMSES_STATE.get("active"):
                    _RAMSES_STATE["observations_while_occupied"] += 1
                    _ramses_write_state()
                    return None
        return original_select(screen)

    def run_connected(endpoint, **kwargs):
        campaign_ledger = kwargs.get("campaign_ledger")
        if not _hourly() or campaign_ledger is None:
            return original_run_connected(endpoint, **kwargs)

        with _RAMSES_LOCK:
            if _RAMSES_STATE.get("active"):
                return dict(
                    status="capacity_censored",
                    boundary="ramses_continuation_position_active",
                    economic_rejection=False,
                    handoff_required=True,
                    paper_only=True,
                )
            asset = campaign_ledger.quote_asset
            safe_asset = "".join(c for c in asset.lower() if c.isalnum())[:24] or "quote"
            ledger_path = f"robinhood-ramses-continuation-{safe_asset}.sqlite"
            proxy = dict(
                status="continuation_active",
                handoff_required=True,
                paper_only=True,
                allocation_authority=False,
                economic_rejection=False,
            )
            _RAMSES_STATE.update(
                active=True,
                proxy=proxy,
                ledger_path=ledger_path,
                paper_capital=int(campaign_ledger.paper_capital),
                quote_asset=asset,
                entry_block=int((kwargs.get("initial_screen") or {}).get("finalized_block") or 0),
                entry_at=int((kwargs.get("initial_screen") or {}).get("finalized_timestamp") or 0),
                lifecycle_prefix=kwargs.get("lifecycle_prefix"),
                segments=[],
                rebalances=0,
                result=None,
                error=None,
                completed_lifecycles=list(_RAMSES_STATE.get("completed_lifecycles") or []),
            )
            _ramses_write_state()

        def target():
            book = None
            try:
                book = RamsesStrategyLedger(
                    ledger_path,
                    paper_capital=int(campaign_ledger.paper_capital),
                    quote_asset=asset,
                )
                _RAMSES_TLS.manager = _RAMSES_STATE
                _RAMSES_TLS.initial_screen = deepcopy(kwargs.get("initial_screen") or {})
                _RAMSES_TLS.costs_by_pool = deepcopy(kwargs.get("costs_by_pool") or {})
                value = lifecycle.run(
                    endpoint,
                    costs_by_pool=kwargs.get("costs_by_pool"),
                    signals_by_pool=kwargs.get("signals_by_pool"),
                    db_path=kwargs.get("db_path"),
                    monitor_poll_seconds=kwargs.get(
                        "monitor_poll_seconds", lifecycle.MONITOR_POLL_SECONDS
                    ),
                    rescan_seconds=kwargs.get("rescan_seconds", lifecycle.RESCAN_SECONDS),
                    initial_screen=kwargs.get("initial_screen"),
                    cost_state=kwargs.get("cost_state"),
                    campaign_ledger=book,
                    lifecycle_prefix=kwargs.get("lifecycle_prefix"),
                )
                with _RAMSES_LOCK:
                    _RAMSES_STATE["result"] = lifecycle.compact_lifecycle_result(value)
                    _RAMSES_STATE["active"] = (
                        (book.reconcile() or {}).get("open_positions", 0) > 0
                    )
                    if not _RAMSES_STATE["active"]:
                        identity=_RAMSES_STATE["result"].get("lifecycle_id")
                        seen={
                            row.get("lifecycle_id")
                            for row in _RAMSES_STATE.setdefault("completed_lifecycles",[])
                            if isinstance(row,dict)
                        }
                        if identity and identity not in seen:
                            _RAMSES_STATE["completed_lifecycles"].append(
                                deepcopy(_RAMSES_STATE["result"])
                            )
                    proxy.clear()
                    proxy.update(_RAMSES_STATE["result"])
                    proxy["handoff_required"] = bool(_RAMSES_STATE["active"])
                    _ramses_write_state()
            except BaseException as exc:
                with _RAMSES_LOCK:
                    _RAMSES_STATE["error"] = dict(
                        type=type(exc).__name__, message=str(exc)[:200]
                    )
                    # The durable ledger, not the thread exception, determines exposure.
                    try:
                        _RAMSES_STATE["active"] = (
                            book is not None and book.reconcile().get("open_positions", 0) > 0
                        )
                    except Exception:
                        _RAMSES_STATE["active"] = True
                    proxy.update(
                        status="continuation_handoff",
                        handoff_required=True,
                        continuation_error_type=type(exc).__name__,
                        continuation_error=str(exc)[:200],
                    )
                    _ramses_write_state()
            finally:
                if book is not None:
                    try:
                        book.close()
                    except Exception:
                        pass
                _RAMSES_TLS.manager = None
                _RAMSES_TLS.initial_screen = None
                _RAMSES_TLS.costs_by_pool = None

        thread = threading.Thread(
            target=target,
            name="ramses-position-continuation",
            daemon=True,
        )
        with _RAMSES_LOCK:
            _RAMSES_STATE["thread"] = thread
        thread.start()
        return proxy

    def persist(result):
        public = deepcopy(result)
        accounting = _ramses_snapshot_accounting()
        with _RAMSES_LOCK:
            continuation = {
                key: deepcopy(value) for key, value in _RAMSES_STATE.items()
                if key not in ("thread", "proxy")
            }
        public["position_continuation"] = continuation
        completed=[
            deepcopy(row) for row in continuation.get("completed_lifecycles",[])
            if isinstance(row,dict)
        ]
        if completed:
            existing=list(public.get("natural_lifecycles") or [])
            seen={
                row.get("lifecycle_id") for row in existing if isinstance(row,dict)
            }
            existing.extend(
                row for row in completed
                if row.get("lifecycle_id") and row.get("lifecycle_id") not in seen
            )
            public["natural_lifecycles"]=existing
            public["connected_lifecycle"]=completed[-1]
        if accounting is not None:
            public["continuation_accounting"] = accounting
        return original_persist(public)

    extended_module.select_qualifier = select_qualifier
    extended_module.run_connected = run_connected
    extended_module._persist_public_result = persist
    atexit.register(_ramses_write_state)


def ramses_continuation_snapshot():
    accounting = _ramses_snapshot_accounting()
    with _RAMSES_LOCK:
        state = {
            key: deepcopy(value) for key, value in _RAMSES_STATE.items()
            if key not in ("thread", "proxy")
        }
    return dict(state=state, accounting=accounting)
