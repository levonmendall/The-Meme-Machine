"""DLMM acquisition v2: redundant discovery + adaptive reconstruction.

This module grants no allocation, signing, submission, ranking, or PnL authority.
Discovery and evidence transport are deliberately separate:
- the public Solana WebSocket is the required high-throughput discovery surface;
- notification logs are classified before any transaction-body read so only likely
  LP-management mutations enter the reconstruction queue;
- authenticated OnFinality HTTP is the reconstruction primary;
- Alchemy remains bounded rescue through the canonical read topology;
- reconstruction is deadline-aware and queue-bounded, never candidate-count-authorized.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import os
import threading
import time

from websockets.sync.client import connect

from . import dlmm
from .provider import Unavailable
from .solana_read_rpc import primary_ws_url


PUBLIC_SOLANA_WS_URL="wss://api.mainnet-beta.solana.com"
PUBLIC_DISCOVERY_PROVIDER="solana_public_mainnet"
ONFINALITY_DISCOVERY_PROVIDER="onfinality_authenticated_solana_mainnet"
DEFAULT_QUEUE_LIMIT=25_000
DEFAULT_RECONSTRUCTION_DEADLINE_SECONDS=1_800
RECONSTRUCTION_DEADLINE_SAFETY_SECONDS=0.5

# Anchor instruction names emitted by the same supported LP-management surface that
# downstream actor extraction can authenticate today. Unknown/truncated DLMM logs are
# queued conservatively rather than treated as irrelevant.
LP_INSTRUCTION_LOG_ACTIONS={
    "AddLiquidity":"add_liquidity",
    "AddLiquidity2":"add_liquidity2",
    "AddLiquidityByStrategy":"add_liquidity_by_strategy",
    "AddLiquidityByStrategy2":"add_liquidity_by_strategy2",
    "AddLiquidityByStrategyOneSide":"add_liquidity_by_strategy_one_side",
    "AddLiquidityByWeight":"add_liquidity_by_weight",
    "AddLiquidityByWeight2":"add_liquidity_by_weight2",
    "AddLiquidityOneSide":"add_liquidity_one_side",
    "AddLiquidityOneSidePrecise":"add_liquidity_one_side_precise",
    "AddLiquidityOneSidePrecise2":"add_liquidity_one_side_precise2",
    "RebalanceLiquidity":"rebalance_liquidity",
    "RemoveAllLiquidity":"remove_all_liquidity",
    "RemoveLiquidity":"remove_liquidity",
    "RemoveLiquidity2":"remove_liquidity2",
    "RemoveLiquidityByRange":"remove_liquidity_by_range",
    "RemoveLiquidityByRange2":"remove_liquidity_by_range2",
    "ClaimFee":"claim_fee",
    "ClaimFee2":"claim_fee2",
}


def classify_dlmm_lp_logs(logs):
    """Cheaply classify finalized notification logs before any HTTP body read.

    Only instruction labels emitted while the DLMM program is at the top of the
    Solana invocation stack are considered. Truncated or structurally ambiguous
    DLMM logs are returned as uncertain so callers can reconstruct them rather than
    silently create false negatives.
    """
    if not isinstance(logs,list):
        return dict(actions=[],likely_lp=False,uncertain=True,reason="missing_logs")
    stack=[];actions=set();uncertain=False
    for line in logs:
        if not isinstance(line,str):
            uncertain=True
            continue
        if "Log truncated" in line:
            uncertain=True
            continue
        if line.startswith("Program ") and " invoke [" in line:
            parts=line.split()
            if len(parts)>=2:
                stack.append(parts[1])
            else:
                uncertain=True
            continue
        if line.startswith("Program ") and (" success" in line or " failed:" in line):
            parts=line.split()
            if len(parts)<2 or not stack or stack[-1]!=parts[1]:
                uncertain=True
                if stack:
                    stack.pop()
            else:
                stack.pop()
            continue
        prefix="Program log: Instruction: "
        if line.startswith(prefix) and stack and stack[-1]==dlmm.PROGRAM:
            label=line[len(prefix):].strip()
            action=LP_INSTRUCTION_LOG_ACTIONS.get(label)
            if action is not None:
                actions.add(action)
    if stack:
        uncertain=True
    actions=sorted(actions)
    return dict(
        actions=actions,likely_lp=bool(actions),uncertain=uncertain,
        reason=("supported_lp_instruction" if actions else
                "ambiguous_dlmm_logs" if uncertain else "no_supported_lp_instruction"),
    )


@dataclass(frozen=True)
class ReconstructionTask:
    identity: str
    kind: str
    deadline: float
    priority: tuple
    payload: dict
    estimated_calls: int = 1


class AdaptiveReconstructionQueue:
    """Bounded, deduplicated deadline queue with provider-headroom governance."""

    def __init__(self, limit=DEFAULT_QUEUE_LIMIT):
        if int(limit)<1:
            raise ValueError("dlmm_reconstruction_queue_limit")
        self.limit=int(limit)
        self._tasks={}
        self.enqueued=0
        self.replaced=0
        self.capacity_skips=0
        self.expired=0
        self.deadline_insufficient=0
        self.provider_headroom_deferrals=0
        self.processed=0

    @staticmethod
    def _key(task):
        return (float(task.deadline),tuple(task.priority),str(task.identity))

    def enqueue(self,task):
        if not isinstance(task,ReconstructionTask):
            raise TypeError("dlmm_reconstruction_task_required")
        prior=self._tasks.get(task.identity)
        if prior is not None:
            if self._key(task)<self._key(prior):
                self._tasks[task.identity]=task
                self.replaced+=1
            return False
        if len(self._tasks)>=self.limit:
            worst_id,worst=max(self._tasks.items(),key=lambda row:self._key(row[1]))
            if self._key(task)>=self._key(worst):
                self.capacity_skips+=1
                return False
            del self._tasks[worst_id]
            self.capacity_skips+=1
        self._tasks[task.identity]=task
        self.enqueued+=1
        return True

    def expire(self,now):
        rows=[identity for identity,task in self._tasks.items()
              if float(task.deadline)<=float(now)]
        for identity in rows:
            del self._tasks[identity]
        self.expired+=len(rows)
        return len(rows)

    def pop_ready(self,now,*,provider_calls,rotation_threshold,
                  request_interval_seconds=0.2):
        self.expire(now)
        if not self._tasks:
            return None
        task=min(self._tasks.values(),key=self._key)
        if int(provider_calls)+int(task.estimated_calls)>int(rotation_threshold):
            self.provider_headroom_deferrals+=1
            return None
        estimate=max(
            0.1,
            float(task.estimated_calls)*float(request_interval_seconds)
            + RECONSTRUCTION_DEADLINE_SAFETY_SECONDS,
        )
        if float(task.deadline)-float(now)<estimate:
            del self._tasks[task.identity]
            self.deadline_insufficient+=1
            return None
        del self._tasks[task.identity]
        self.processed+=1
        return task

    def __len__(self):
        return len(self._tasks)

    def status(self,now=None):
        next_deadline=(
            min(float(task.deadline) for task in self._tasks.values())
            if self._tasks else None
        )
        return dict(
            scheduler="adaptive_dlmm_reconstruction_queue_v1",
            queue_depth=len(self._tasks),
            queue_limit=self.limit,
            enqueued=self.enqueued,
            replaced=self.replaced,
            capacity_skips=self.capacity_skips,
            expired=self.expired,
            deadline_insufficient=self.deadline_insufficient,
            provider_headroom_deferrals=self.provider_headroom_deferrals,
            processed=self.processed,
            next_deadline_seconds=(
                None if now is None or next_deadline is None
                else max(0.0,next_deadline-float(now))
            ),
        )


class UnionSignatureLedger:
    """Deduplicate finalized DLMM signatures across discovery providers."""

    def __init__(self):
        self._rows={}
        self.provider_notifications=Counter()
        self.provider_signatures=Counter()
        self.provider_lp_candidates=Counter()

    def observe(self,provider,signature,slot,observed_at,logs=None):
        provider=str(provider);signature=str(signature)
        self.provider_notifications[provider]+=1
        relevance=classify_dlmm_lp_logs(logs)
        row=self._rows.get(signature)
        if row is None:
            row=dict(
                signature=signature,slot=int(slot),
                first_observed_at=float(observed_at),providers=set(),
                relevance_actions=set(),relevance_uncertain=False,
                relevance_reasons=set(),
            )
            self._rows[signature]=row
        else:
            row["slot"]=max(int(row["slot"]),int(slot))
        row["relevance_actions"].update(relevance["actions"])
        row["relevance_uncertain"]=bool(
            row["relevance_uncertain"] or relevance["uncertain"])
        row["relevance_reasons"].add(relevance["reason"])
        if provider not in row["providers"]:
            row["providers"].add(provider)
            self.provider_signatures[provider]+=1
        if (relevance["likely_lp"] or relevance["uncertain"]):
            self.provider_lp_candidates[provider]+=1

    @staticmethod
    def _public_row(row):
        return dict(
            signature=row["signature"],slot=row["slot"],
            first_observed_at=row["first_observed_at"],
            providers=sorted(row["providers"]),
            relevance_actions=sorted(row["relevance_actions"]),
            relevance_uncertain=bool(row["relevance_uncertain"]),
            relevance_reasons=sorted(row["relevance_reasons"]),
        )

    def rows(self):
        return [
            self._public_row(row)
            for row in sorted(
                self._rows.values(),
                key=lambda x:(x["first_observed_at"],x["slot"],x["signature"]))
        ]

    def candidate_rows(self):
        return [
            self._public_row(row)
            for row in sorted(
                self._rows.values(),
                key=lambda x:(x["first_observed_at"],x["slot"],x["signature"]))
            if row["relevance_actions"] or row["relevance_uncertain"]
        ]

    def status(self):
        public={s for s,r in self._rows.items()
                if PUBLIC_DISCOVERY_PROVIDER in r["providers"]}
        onfinality={s for s,r in self._rows.items()
                    if ONFINALITY_DISCOVERY_PROVIDER in r["providers"]}
        both=public & onfinality
        union=public | onfinality
        return dict(
            unique_signatures=len(self._rows),
            provider_notifications=dict(sorted(self.provider_notifications.items())),
            provider_unique_signatures=dict(sorted(self.provider_signatures.items())),
            provider_lp_candidate_notifications=dict(
                sorted(self.provider_lp_candidates.items())),
            likely_lp_signatures=sum(bool(r["relevance_actions"]) for r in self._rows.values()),
            uncertain_signatures=sum(bool(r["relevance_uncertain"]) for r in self._rows.values()),
            reconstruction_candidates=sum(
                bool(r["relevance_actions"]) or bool(r["relevance_uncertain"])
                for r in self._rows.values()),
            filtered_without_http=sum(
                not r["relevance_actions"] and not r["relevance_uncertain"]
                for r in self._rows.values()),
            overlap_signatures=len(both),
            jaccard=(None if not union else len(both)/len(union)),
            public_coverage_of_union=(None if not union else len(public)/len(union)),
            onfinality_coverage_of_union=(None if not union else len(onfinality)/len(union)),
        )


class _StreamCollector:
    def __init__(self,provider,url,ledger,stop_event,ready_event):
        self.provider=provider
        self.url=url
        self.ledger=ledger
        self.stop_event=stop_event
        self.ready_event=ready_event
        self.connections=0
        self.reconnects=0
        self.subscription_errors=0
        self.parse_errors=0
        self.disconnect_kinds=Counter()

    def run(self):
        ever=False
        while not self.stop_event.is_set():
            try:
                with connect(
                    self.url,open_timeout=10,ping_interval=20,ping_timeout=20,
                    close_timeout=5,max_size=2_000_000,max_queue=512,
                ) as ws:
                    request={"jsonrpc":"2.0","id":1,"method":"logsSubscribe","params":[
                        {"mentions":[dlmm.PROGRAM]},{"commitment":"finalized"}]}
                    ws.send(json.dumps(request))
                    ack=json.loads(ws.recv(timeout=10))
                    if ack.get("error") or not isinstance(ack.get("result"),int):
                        self.subscription_errors+=1
                        raise RuntimeError("dlmm_subscription_rejected")
                    if ever:self.reconnects+=1
                    ever=True;self.connections+=1;self.ready_event.set()
                    while not self.stop_event.is_set():
                        try:
                            payload=json.loads(ws.recv(timeout=1))
                        except TimeoutError:
                            continue
                        except json.JSONDecodeError:
                            self.parse_errors+=1;continue
                        try:
                            if payload.get("method")!="logsNotification":
                                continue
                            result=payload["params"]["result"]
                            value=result["value"]
                            if value.get("err") is not None:
                                continue
                            self.ledger.observe(
                                self.provider,value["signature"],
                                result["context"]["slot"],time.time(),
                                value.get("logs"))
                        except (KeyError,TypeError,ValueError):
                            self.parse_errors+=1
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                self.disconnect_kinds[type(exc).__name__]+=1
                self.stop_event.wait(1)

    def status(self):
        return dict(
            provider=self.provider,connections=self.connections,
            reconnects=self.reconnects,subscription_errors=self.subscription_errors,
            parse_errors=self.parse_errors,
            disconnect_kinds=dict(sorted(self.disconnect_kinds.items())),
        )


def discovery_streams(environ=None):
    """Return public discovery plus an explicitly opt-in authenticated diagnostic."""
    env=os.environ if environ is None else environ
    rows=[(PUBLIC_DISCOVERY_PROVIDER,PUBLIC_SOLANA_WS_URL)]
    include_auth=str(env.get("MM_DLMM_INCLUDE_ONFINALITY_DISCOVERY_WS","")).lower() in (
        "1","true","yes","on")
    if include_auth:
        try:
            auth=primary_ws_url(env,require_authenticated=True)
        except (Unavailable,TypeError):
            auth=None
        if auth:
            rows.append((ONFINALITY_DISCOVERY_PROVIDER,auth))
    return rows


def collect_program_union(duration_seconds,*,environ=None,require_public=True):
    duration=max(1,int(duration_seconds))
    ledger=UnionSignatureLedger();stop=threading.Event()
    collectors=[];threads=[]
    for provider,url in discovery_streams(environ):
        ready=threading.Event()
        collector=_StreamCollector(provider,url,ledger,stop,ready)
        thread=threading.Thread(target=collector.run,daemon=True)
        collectors.append((collector,ready));threads.append(thread);thread.start()

    start_wait=time.monotonic()
    public_ready=False
    for collector,ready in collectors:
        remaining=max(0.1,20-(time.monotonic()-start_wait))
        ok=ready.wait(remaining)
        if collector.provider==PUBLIC_DISCOVERY_PROVIDER:
            public_ready=ok
    if require_public and not public_ready:
        stop.set()
        raise RuntimeError("dlmm_public_discovery_stream_unavailable")

    started=int(time.time());deadline=time.monotonic()+duration
    while time.monotonic()<deadline:
        stop.wait(min(1,max(0,deadline-time.monotonic())))
    stop.set()
    for thread in threads:thread.join(timeout=5)
    ended=int(time.time())
    return dict(
        started=started,ended=ended,duration_seconds=duration,
        signatures=ledger.rows(),lp_candidates=ledger.candidate_rows(),
        union=ledger.status(),
        streams=[collector.status() for collector,_ in collectors],
        discovery_authority="union_finalized_dlmm_program_stream",
        pnl_authority=False,allocation_authority=False,
    )
