"""Bounded deadline-aware candidate queue for Robinhood directional evidence.

This is acquisition scheduling only. It never changes qualification thresholds or
freshness rules; the authoritative evaluator still enforces the exact five-second
state gate.
"""
from __future__ import annotations

from collections import Counter
import time


class DeadlineEvidenceQueue:
    def __init__(self, *, limit=10_000, nominal_deadline_seconds=5.0):
        if not 1 <= int(limit) <= 100_000:
            raise ValueError("invalid_evidence_queue_limit")
        if not 1.0 <= float(nominal_deadline_seconds) <= 10.0:
            raise ValueError("invalid_evidence_queue_deadline")
        self.limit=int(limit)
        self.nominal_deadline_seconds=float(nominal_deadline_seconds)
        self.rows={}
        self.counts=Counter()

    @staticmethod
    def _key(event):
        return (
            str(event.get("transactionHash") or ""),
            str(event.get("logIndex") or ""),
        )

    @staticmethod
    def _order(row):
        event=row["event"]
        try:block=int(event.get("blockNumber","0x0"),16)
        except (TypeError,ValueError):block=0
        try:txi=int(event.get("transactionIndex","0x0"),16)
        except (TypeError,ValueError):txi=0
        try:logi=int(event.get("logIndex","0x0"),16)
        except (TypeError,ValueError):logi=0
        return (float(row["deadline"]),block,txi,logi,row["key"])

    def enqueue(self,event,*,now=None):
        observed=time.time() if now is None else float(now)
        key=self._key(event)
        if not all(key):
            self.counts["invalid"]+=1
            return False
        if key in self.rows:
            self.counts["duplicate"]+=1
            return False
        row=dict(
            key=key,event=event,queued_at=observed,
            deadline=observed+self.nominal_deadline_seconds,
        )
        if len(self.rows)>=self.limit:
            worst_key,worst=max(
                self.rows.items(),key=lambda item:self._order(item[1])
            )
            if self._order(row)>=self._order(worst):
                self.counts["capacity_skipped"]+=1
                return False
            del self.rows[worst_key]
            self.counts["capacity_evicted"]+=1
        self.rows[key]=row
        self.counts["enqueued"]+=1
        return True

    def expire(self,*,now=None):
        observed=time.time() if now is None else float(now)
        expired=[k for k,row in self.rows.items() if row["deadline"]<=observed]
        for key in expired:
            del self.rows[key]
        self.counts["expired_before_evidence"]+=len(expired)
        return len(expired)

    def pop(self,*,now=None,minimum_remaining_seconds=0.0):
        observed=time.time() if now is None else float(now)
        self.expire(now=observed)
        if not self.rows:
            return None
        while self.rows:
            key,row=min(self.rows.items(),key=lambda item:self._order(item[1]))
            del self.rows[key]
            remaining=float(row["deadline"])-observed
            if remaining < float(minimum_remaining_seconds):
                self.counts["deadline_insufficient"]+=1
                continue
            self.counts["processed"]+=1
            row["remaining_seconds_at_dispatch"]=remaining
            return row
        return None

    def telemetry(self):
        return dict(
            depth=len(self.rows),limit=self.limit,
            nominal_deadline_seconds=self.nominal_deadline_seconds,
            **dict(self.counts),
        )
