"""Incremental finalized PumpSwap history cache for prospective evidence.

The first read backfills toward graduation. Later reads request only signatures newer
than the previously observed head and decode only unseen transactions. Signature
coverage and transaction coverage are tracked separately and both must be complete.
"""
from __future__ import annotations

import time

from .provider import Unavailable
from .pump_acceleration_evidence import pumpswap_trade_events


class IncrementalPumpSwapHistory:
    def __init__(
        self,pool,graduation_time,page_limit=96,max_backfill_pages=2,max_new_pages=4,
        max_tx_per_refresh=128,broker=None,stream_key="pumpswap_program",
    ):
        self.pool=str(pool)
        self.graduation_time=int(graduation_time)
        self.page_limit=int(page_limit)
        self.max_backfill_pages=int(max_backfill_pages)
        self.max_new_pages=int(max_new_pages)
        self.max_tx_per_refresh=int(max_tx_per_refresh)
        self.signature_rows={}
        self.processed=set()
        self.events={}
        self.newest_signature=None
        self.oldest_signature=None
        self.signature_coverage_complete=False
        self.history_exhausted=False
        self.capacity_loss=False
        self.unknown_block_times=0
        self.pages=0
        self.refreshes=0
        self.tx_failures=0
        self.broker=broker
        self.stream_key=str(stream_key)
        self.history_scope="pumpswap_history"
        self.stream_pending_transactions=0
        self.stream_events_seen=0
        self.stream_hydrated_transactions=0
        self.stream_last_slot=0
        self.decision_bootstrap_attempts=0
        self.decision_bootstrap_pages=0
        self.decision_bootstrap_complete=False
        self.decision_bootstrap_capacity_loss=False
        self.restored_signature_rows=0
        if self.broker is not None:
            restored=self.broker.signature_rows(
                self.history_scope,self.pool)
            if restored:
                self._remember(restored)
                self._coverage()
                self.restored_signature_rows=len(restored)

    @staticmethod
    def _valid_rows(rows):
        if not isinstance(rows,list):
            raise Unavailable("invalid_pumpswap_history")
        return [r for r in rows if isinstance(r,dict) and r.get("signature")]

    def _fetch(self,rpc,*,before=None,until=None,limit=None):
        cfg={"limit":int(limit or self.page_limit),"commitment":"finalized"}
        if before:
            cfg["before"]=str(before)
        if until:
            cfg["until"]=str(until)
        rows=self._valid_rows(rpc.call(
            "getSignaturesForAddress",[self.pool,cfg],True))
        self.pages+=1
        return rows

    def _remember(self,rows):
        if not rows:
            return
        if self.broker is not None:
            self.broker.remember_signatures(
                self.history_scope,self.pool,rows)
        for row in rows:
            sig=str(row["signature"])
            prior=self.signature_rows.get(sig)
            self.signature_rows[sig]=dict(row)
            if prior is None and row.get("blockTime") is None:
                self.unknown_block_times+=1
        known=[
            r for r in self.signature_rows.values()
            if r.get("blockTime") is not None
        ]
        if known:
            newest=max(
                known,key=lambda r:(int(r["blockTime"]),int(r.get("slot") or -1)))
            oldest=min(
                known,key=lambda r:(int(r["blockTime"]),int(r.get("slot") or -1)))
            self.newest_signature=str(newest["signature"])
            self.oldest_signature=str(oldest["signature"])

    def _coverage(self):
        known=[
            int(r["blockTime"]) for r in self.signature_rows.values()
            if r.get("blockTime") is not None
        ]
        reached=bool(known and min(known)<=self.graduation_time)
        self.signature_coverage_complete=bool(reached or self.history_exhausted)

    def _new_head(self,rpc):
        old_head=self.newest_signature
        if old_head is None:
            rows=self._fetch(rpc,limit=self.page_limit)
            self._remember(rows)
            if len(rows)<self.page_limit:
                self.history_exhausted=True
            return
        before=None
        total=0
        for _ in range(self.max_new_pages):
            rows=self._fetch(
                rpc,before=before,until=old_head,
                limit=min(1000,self.page_limit*4))
            if not rows:
                break
            total+=len(rows)
            self._remember(rows)
            before=rows[-1]["signature"]
            if len(rows)<min(1000,self.page_limit*4):
                break
        else:
            if total:
                self.capacity_loss=True
        if self.signature_rows:
            newest=max(
                self.signature_rows.values(),
                key=lambda r:(int(r.get("blockTime") or -1),int(r.get("slot") or -1)))
            self.newest_signature=str(newest["signature"])

    def _backfill(self,rpc):
        self._coverage()
        if self.signature_coverage_complete:
            return
        before=self.oldest_signature
        for _ in range(self.max_backfill_pages):
            rows=self._fetch(rpc,before=before,limit=self.page_limit)
            if not rows:
                self.history_exhausted=True
                break
            self._remember(rows)
            before=rows[-1]["signature"]
            times=[int(r["blockTime"]) for r in rows if r.get("blockTime") is not None]
            if times and min(times)<=self.graduation_time:
                break
            if len(rows)<self.page_limit:
                self.history_exhausted=True
                break
        self._coverage()

    def _ingest_stream_window(
        self,rpc,now,window_seconds=30,hydration_kind="pump_window"
    ):
        if self.broker is None:
            return
        now=int(now);cutoff=now-int(window_seconds)
        rows=self.broker.recent_events(
            self.stream_key,since=cutoff-2,after_slot=None)
        self.stream_events_seen+=len(rows)
        signatures=[];slot_by_sig={}
        for row in rows:
            sig=row.get("signature")
            if not isinstance(sig,str) or not sig:
                continue
            signatures.append(sig)
            slot_by_sig[sig]=int(row["slot"])
            self.stream_last_slot=max(self.stream_last_slot,int(row["slot"]))
        if not signatures:
            self.stream_pending_transactions=0
            return
        txs,meta=self.broker.hydrate_transactions(
            rpc,signatures,kind=str(hydration_kind),
            deadline=time.time()+4.0,max_version=1,batch_size=8)
        self.stream_pending_transactions=int(meta["pending"])
        self.stream_hydrated_transactions+=int(meta["hydrated"])
        for sig in signatures:
            tx=txs.get(sig)
            if not isinstance(tx,dict):
                continue
            bt=tx.get("blockTime")
            if type(bt) is not int or not cutoff-2<=int(bt)<=now:
                continue
            row=dict(
                signature=sig,slot=int(tx.get("slot") or slot_by_sig[sig]),
                blockTime=int(bt),err=(tx.get("meta") or {}).get("err"),
                confirmationStatus="finalized",
            )
            self._remember([row])
            if sig in self.processed or row.get("err"):
                continue
            self.processed.add(sig)
            for event in pumpswap_trade_events(tx):
                if event.get("pool")!=self.pool:
                    continue
                event["id"]=f'{sig}:{event["index"]}'
                self.events[event["id"]]=event

    def _stream_window_complete(self,now,window_seconds=30):
        if self.broker is None:
            return False
        status=self.broker.stream_status(
            self.stream_key,now,window_seconds)
        return bool(status.get("covered") and self.stream_pending_transactions==0)

    def _bootstrap_decision_window(self,rpc,now,window_seconds=30):
        """Bounded HTTP bootstrap while a candidate-specific pool stream warms."""
        if self.broker is None or self._stream_window_complete(now,window_seconds):
            self.decision_bootstrap_complete=True
            return
        if self.decision_bootstrap_complete or self.decision_bootstrap_capacity_loss:
            return
        if self.decision_bootstrap_attempts>=3:
            return

        self.decision_bootstrap_attempts+=1
        cutoff=int(now)-int(window_seconds)
        before=None
        page_limit=min(96,self.page_limit)
        pages=0
        reached=False
        for _ in range(max(1,self.max_backfill_pages+1)):
            rows=self._fetch(rpc,before=before,limit=page_limit)
            pages+=1
            self._remember(rows)
            if not rows:
                self.history_exhausted=True
                reached=True
                break
            times=[
                int(row["blockTime"]) for row in rows
                if row.get("blockTime") is not None
            ]
            if times and min(times)<=cutoff:
                reached=True
                break
            if len(rows)<page_limit:
                self.history_exhausted=True
                reached=True
                break
            before=rows[-1]["signature"]
        self.decision_bootstrap_pages+=pages
        if reached:
            self.decision_bootstrap_complete=True
        elif pages>=max(1,self.max_backfill_pages+1):
            self.decision_bootstrap_capacity_loss=True

    def _decode_pending(self,rpc,now,kind="research_history"):
        cutoff=int(now)-30
        recent=[]
        older=[]
        for row in self.signature_rows.values():
            sig=str(row["signature"])
            if sig in self.processed or row.get("err"):
                continue
            bt=row.get("blockTime")
            if bt is None:
                continue
            bt=int(bt)
            if not self.graduation_time<=bt<=int(now):
                if bt<self.graduation_time:
                    self.processed.add(sig)
                continue
            target=recent if bt>=cutoff else older
            target.append(row)
        # Finish the live 30-second decision window first. Older history is useful
        # for second-leg shape, but must never starve current continuation evidence.
        recent.sort(key=lambda r:(-int(r.get("blockTime") or 0),-int(r.get("slot") or 0)))
        older.sort(key=lambda r:(-int(r.get("blockTime") or 0),-int(r.get("slot") or 0)))
        if recent:
            pending=recent[:self.max_tx_per_refresh]
        else:
            pending=older[:self.max_tx_per_refresh]
        for start in range(0,len(pending),16):
            chunk=pending[start:start+16]
            signatures=[str(r["signature"]) for r in chunk]
            if self.broker is not None:
                txmap,meta=self.broker.hydrate_transactions(
                    rpc,signatures,kind=str(kind),
                    deadline=time.time()+6.0,max_version=1,batch_size=8)
                txs=[txmap.get(sig) for sig in signatures]
                self.tx_failures+=int(meta["pending"])
            else:
                params=[[r["signature"],{
                    "encoding":"json","commitment":"finalized",
                    "maxSupportedTransactionVersion":1,
                }] for r in chunk]
                try:
                    txs=rpc.call_many("getTransaction",params,True,batch_size=16)
                except Unavailable:
                    self.tx_failures+=len(chunk)
                    continue
            for row,tx in zip(chunk,txs):
                sig=str(row["signature"])
                if tx is None:
                    if self.broker is None:
                        self.tx_failures+=1
                    continue
                self.processed.add(sig)
                for event in pumpswap_trade_events(tx):
                    if event.get("pool")!=self.pool:
                        continue
                    event["id"]=f'{sig}:{event["index"]}'
                    self.events[event["id"]]=event

    def decision_window_status(self,now,window_seconds=30):
        now=int(now);cutoff=now-int(window_seconds)
        known=[
            int(r["blockTime"]) for r in self.signature_rows.values()
            if r.get("blockTime") is not None and int(r["blockTime"])<=now
        ]
        signature_complete=bool(
            self._stream_window_complete(now,window_seconds)
            or self.history_exhausted
            or (known and min(known)<=cutoff)
        )
        pending=0
        for row in self.signature_rows.values():
            sig=str(row["signature"]);bt=row.get("blockTime")
            if sig in self.processed or row.get("err") or bt is None:
                continue
            if cutoff<=int(bt)<=now:
                pending+=1
        complete=bool(
            signature_complete
            and self.unknown_block_times==0
            and pending==0
            and (self.broker is None or self.stream_pending_transactions==0))
        return dict(
            complete=complete,window_seconds=int(window_seconds),
            signature_complete=signature_complete,pending_transactions=pending,
            cutoff=cutoff,
        )

    def decision_rows(self,now,window_seconds=30):
        cutoff=int(now)-int(window_seconds)
        return sorted(
            (dict(e) for e in self.events.values()
             if cutoff<=int(e.get("market_time",0))<=int(now)),
            key=lambda e:(int(e["market_time"]),int(e.get("slot",0)),int(e.get("index",0))),
        )


    def refresh(
        self,rpc,now,*,research=False,hydration_kind="pump_window"
    ):
        self.refreshes+=1
        if self.broker is not None:
            # Current decision evidence is stream-first. Historical page reads are
            # deferred until second-leg research actually needs them.
            self._ingest_stream_window(
                rpc,now,30,hydration_kind=hydration_kind)
            if not self._stream_window_complete(now,30):
                self._bootstrap_decision_window(rpc,now,30)
                self._decode_pending(
                    rpc,now,kind=str(hydration_kind))
            if research:
                self._new_head(rpc)
                self._backfill(rpc)
                self._decode_pending(rpc,now,kind="research_history")
        else:
            self._new_head(rpc)
            self._backfill(rpc)
            self._decode_pending(rpc,now)
        return self.rows(now)

    def pending_relevant(self,now):
        total=0
        for row in self.signature_rows.values():
            sig=str(row["signature"])
            bt=row.get("blockTime")
            if sig in self.processed or row.get("err") or bt is None:
                continue
            if self.graduation_time<=int(bt)<=int(now):
                total+=1
        return total

    def complete(self,now):
        return bool(
            self.signature_coverage_complete
            and not self.capacity_loss
            and self.unknown_block_times==0
            and self.pending_relevant(now)==0
        )

    def rows(self,now):
        return sorted(
            (dict(e) for e in self.events.values()
             if self.graduation_time<=int(e.get("market_time",0))<=int(now)),
            key=lambda e:(int(e["market_time"]),int(e.get("slot",0)),int(e.get("index",0))),
        )

    def status(self,now):
        return dict(
            complete=self.complete(now),
            signature_coverage_complete=self.signature_coverage_complete,
            history_exhausted=self.history_exhausted,
            capacity_loss=self.capacity_loss,
            signatures=len(self.signature_rows),
            processed_transactions=len(self.processed),
            pending_transactions=self.pending_relevant(now),
            events=len(self.events),pages=self.pages,refreshes=self.refreshes,
            unknown_block_times=self.unknown_block_times,
            transaction_failures=self.tx_failures,
            stream_pending_transactions=self.stream_pending_transactions,
            stream_events_seen=self.stream_events_seen,
            stream_hydrated_transactions=self.stream_hydrated_transactions,
            stream_last_slot=self.stream_last_slot,
            decision_bootstrap_attempts=self.decision_bootstrap_attempts,
            decision_bootstrap_pages=self.decision_bootstrap_pages,
            decision_bootstrap_complete=self.decision_bootstrap_complete,
            decision_bootstrap_capacity_loss=self.decision_bootstrap_capacity_loss,
            restored_signature_rows=self.restored_signature_rows,
            persisted_signature_rows=(
                0 if self.broker is None else len(
                    self.broker.signature_rows(
                        self.history_scope,self.pool))
            ),
            stream_status=(
                None if self.broker is None
                else self.broker.stream_status(self.stream_key,now,30)
            ),
            newest_signature=self.newest_signature,
            oldest_signature=self.oldest_signature,
            decision_window=self.decision_window_status(now,30),
        )
