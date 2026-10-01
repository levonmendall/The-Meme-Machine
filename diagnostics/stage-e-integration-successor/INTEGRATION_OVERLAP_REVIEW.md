# Integration overlap review

PAPER ONLY. Stage E RED; Stage F NOT_STARTED. No certification credit.

The historical housekeeping patch context predates M1/A2; it was not blindly
applied and no historical diagnostic branch was merged. The treatment at
`d4068d4fa177225daf8780ee7c9765977f4b8793` has SHA256
`f4d3b0399dcfbe43b968ef0a901be73efe187f1a3ecdc79b16f5defb177f6f2d`.

BASE: `dc08f9064cf5e37b63f383f52aa709d0afc1723f`.
M1: `b11b16fbdc4ea0312b2c6f51de37e4d68e1f2da1`.
M1/A2: `4d386498b3dc848e1ba27d11dd8d61841ba426d1`.

## meme_machine/solana_maintenance_runtime.py

M1 supplies exact interruption classification, one bounded completion-accounting
retry and durable receipt acknowledgement. A2 inherits those semantics. The
historical housekeeping intent is to service the sole retirement peer blocker
inside an ALREADY-ADMITTED retirement turn using its exact fresh observation,
generation, existing decision time and effective deadlines. The integrated
selector is structurally identical to the reviewed helper: t+E < D_HK <=
t+2E+O, every other active D_scope > t+2E+O, ready pending archive receipt and
positive native HK demand. E=O=3, so the peer window is 9 seconds. Safety,
drought and active recovery clocks are all respected. No second choice or
admission is introduced. The integrated ordinary callback remains zero-argument;
only an eligible turn enters the reversible housekeeping context. The M1/A2
completion finally block, `_complete_decision` and `_cooperative` are preserved.

### BASE

```python
                                    self.arbiter.origin.pop(receipt_key,None)
                                    result['snapshot']=snapshot
                        else:
                            # Native method still rechecks all pins, floors and
                            # generation-relevant evidence at mutation time.
                            result['retention_outcome']=self.state.retention()
                    finally:
                        progress,records=self._native_progress(self.last_progress,needs,decision.side)
                        self.arbiter.complete(decision,self.monotonic(),progress,record_progress=records)
                        event.update(durable_progress=progress,durable_records=records)
            end=self.monotonic()
            if end-start>self.leases.execution:
                raise EvidenceUnavailable('maintenance_execution_lease_exceeded')
            event['execution']=end-start
            self.execution_total += end-start
            self._record(event)
            return result
```

### M1

```python
                                    self.arbiter.origin.pop(receipt_key,None)
                                    result['snapshot']=snapshot
                        else:
                            # Native method still rechecks all pins, floors and
                            # generation-relevant evidence at mutation time.
                            result['retention_outcome']=self.state.retention()
                    except BaseException as exc:
                        execution_error = exc
                        event['operation_error'] = type(exc).__name__+':'+str(exc)[:120]
                        raise
                    finally:
                        self._complete_decision(decision, needs, event, execution_error,
                                                start+self.leases.execution)
            end=self.monotonic()
            if end-start>self.leases.execution:
                raise EvidenceUnavailable('maintenance_execution_lease_exceeded')
            event['execution']=end-start
```

### M1/A2

```python
                                    self.arbiter.origin.pop(receipt_key,None)
                                    result['snapshot']=snapshot
                        else:
                            # Native method still rechecks all pins, floors and
                            # generation-relevant evidence at mutation time.
                            result['retention_outcome']=self.state.retention()
                    except BaseException as exc:
                        execution_error = exc
                        event['operation_error'] = type(exc).__name__+':'+str(exc)[:120]
                        raise
                    finally:
                        self._complete_decision(decision, needs, event, execution_error,
                                                start+self.leases.execution)
            end=self.monotonic()
            if end-start>self.leases.execution:
                raise EvidenceUnavailable('maintenance_execution_lease_exceeded')
            event['execution']=end-start
```

### Integrated result

```python
                                    result['snapshot']=snapshot
                        else:
                            # Native method still rechecks all pins, floors and
                            # generation-relevant evidence at mutation time.
                            if self._housekeeping_first(decision,observation,needs,ready,flight):
                                with self.state.housekeeping_retention():
                                    result['retention_outcome']=self.state.retention()
                            else:
                                result['retention_outcome']=self.state.retention()
                    except BaseException as exc:
                        execution_error = exc
                        event['operation_error'] = type(exc).__name__+':'+str(exc)[:120]
                        raise
                    finally:
                        self._complete_decision(decision, needs, event, execution_error,
                                                start+self.leases.execution)
            end=self.monotonic()
```

### Full exact delta from M1/A2

```diff
diff --git a/meme_machine/solana_maintenance_runtime.py b/meme_machine/solana_maintenance_runtime.py
index 44d627be..ee777e5c 100644
--- a/meme_machine/solana_maintenance_runtime.py
+++ b/meme_machine/solana_maintenance_runtime.py
@@ -323,0 +324,28 @@ class MaintenanceRuntime:
+    def _housekeeping_first(self,decision,observation,needs,ready,flight):
+        """Use only this already-admitted turn's fresh effective deadlines."""
+        if (decision is None or decision is not self.arbiter.pending or
+                decision.side!='retirement' or observation is not self.last_observation or
+                observation.generation!=self.generation or
+                self.state.fence.session!=self.generation or
+                flight.generation!=self.generation or flight.pending is None or
+                not ready['archive'] or observation.housekeeping<=0):
+            return False
+        active=[n for n in needs if n.side=='retirement' and n.units]
+        housekeeping=[n for n in active if n.scope=='__housekeeping__']
+        if len(housekeeping)!=1:
+            return False
+        def effective(n):
+            # Exactly choose()'s safety, successful-service drought and, when
+            # active, recovery minimum. Origins were established by that choice.
+            deadline=min(n.safety_deadline,
+                         self.arbiter.origin[n.side,n.scope]+self.leases.drought)
+            if n.recovery_excess:
+                deadline=min(deadline,n.recovery_deadline)
+            return deadline
+        now=decision.started
+        peer_window=now+2*self.leases.execution+self.leases.owner
+        return (now+self.leases.execution<effective(housekeeping[0])<=peer_window and
+                all(effective(n)>peer_window for n in active
+                    if n.scope!='__housekeeping__'))
+
+
@@ -409 +437,5 @@ class MaintenanceRuntime:
-                            result['retention_outcome']=self.state.retention()
+                            if self._housekeeping_first(decision,observation,needs,ready,flight):
+                                with self.state.housekeeping_retention():
+                                    result['retention_outcome']=self.state.retention()
+                            else:
+                                result['retention_outcome']=self.state.retention()
```

## meme_machine/solana_evidence_service.py

A2 modifies owner admission and source placement outside ordinary retention.
Its owner control, admission implementation and original tests remain exact.
The historical wrapper forwarded a housekeeping option unconditionally; doing
that at a runtime call site would break existing zero-argument custom overrides.
The contextual port preserves callback signatures and forwards the writer
keyword only when eligible. `housekeeping_retention()` restores its prior flag
on every return or exception. No FIFO, urgency, source charge, wait accounting,
fast-resubmission barrier, queue or callback-signature redesign is made.

### BASE

```python
    def retention(self):
        import sqlite3
        from .solana_retention_outcome import RetentionProgress
        if self.writer.db.in_transaction:
            raise EvidenceUnavailable('retention_inside_source_transaction')
        self.writer.last_retention_progress=RetentionProgress()
        try:
            self._storage_stage('retention',lambda:self.writer.retain(
                time.time()-180,max_records=1000,archive_first=False,checkpoint=False))
        except EvidenceUnavailable as exc:
            if str(exc)!='evidence_background_yield':raise
            self.writer.last_retention_progress.interrupted=True
```

### M1

```python
    def retention(self):
        import sqlite3
        from .solana_retention_outcome import RetentionProgress
        if self.writer.db.in_transaction:
            raise EvidenceUnavailable('retention_inside_source_transaction')
        self.writer.last_retention_progress=RetentionProgress()
        try:
            self._storage_stage('retention',lambda:self.writer.retain(
                time.time()-180,max_records=1000,archive_first=False,checkpoint=False))
        except EvidenceUnavailable as exc:
            if str(exc)!='evidence_background_yield':raise
            self.writer.last_retention_progress.interrupted=True
```

### M1/A2

```python
    def retention(self):
        import sqlite3
        from .solana_retention_outcome import RetentionProgress
        if self.writer.db.in_transaction:
            raise EvidenceUnavailable('retention_inside_source_transaction')
        self.writer.last_retention_progress=RetentionProgress()
        try:
            self._storage_stage('retention',lambda:self.writer.retain(
                time.time()-180,max_records=1000,archive_first=False,checkpoint=False))
        except EvidenceUnavailable as exc:
            if str(exc)!='evidence_background_yield':raise
            self.writer.last_retention_progress.interrupted=True
```

### Integrated result

```python
        from .solana_retention_outcome import RetentionProgress
        if self.writer.db.in_transaction:
            raise EvidenceUnavailable('retention_inside_source_transaction')
        self.writer.last_retention_progress=RetentionProgress()
        housekeeping_first=housekeeping_first or getattr(self,'_housekeeping_retention',False)
        retention_options=dict(housekeeping_first=True) if housekeeping_first else {}
        try:
            self._storage_stage('retention',lambda:self.writer.retain(
                time.time()-180,max_records=1000,archive_first=False,checkpoint=False,
                **retention_options))
        except EvidenceUnavailable as exc:
            if str(exc)!='evidence_background_yield':raise
            self.writer.last_retention_progress.interrupted=True
        except sqlite3.OperationalError as exc:
            # A prior interrupted query is not evidence that a later disk/busy
            # error was a cooperative yield. Preserve unrelated storage failures.
            if (str(exc) != 'interrupted' or
```

### Full exact delta from M1/A2

```diff
diff --git a/meme_machine/solana_evidence_service.py b/meme_machine/solana_evidence_service.py
index c57bef96..27e270b4 100644
--- a/meme_machine/solana_evidence_service.py
+++ b/meme_machine/solana_evidence_service.py
@@ -7,0 +8 @@ required to seal it. Silence, root notifications and socket ACKs never seal data
+from contextlib import contextmanager
@@ -749 +750,11 @@ class ServiceState:
-    def retention(self):
+    @contextmanager
+    def housekeeping_retention(self):
+        """One owner-affine eligible turn; ordinary retirement hooks stay zero-argument."""
+        previous=getattr(self,'_housekeeping_retention',False)
+        self._housekeeping_retention=True
+        try:
+            yield
+        finally:
+            self._housekeeping_retention=previous
+
+    def retention(self, *, housekeeping_first=False):
@@ -754,0 +766,2 @@ class ServiceState:
+        housekeeping_first=housekeeping_first or getattr(self,'_housekeeping_retention',False)
+        retention_options=dict(housekeeping_first=True) if housekeeping_first else {}
@@ -757 +770,2 @@ class ServiceState:
-                time.time()-180,max_records=1000,archive_first=False,checkpoint=False))
+                time.time()-180,max_records=1000,archive_first=False,checkpoint=False,
+                **retention_options))
```

## meme_machine/solana_evidence_plane.py

BASE/M1/A2 retire scopes before ordinary GC. The historical intent moves ONE
invocation of the existing native bounded three-table GC batch before lower-
urgency scope retirement. The extracted helper AST matches A2's original block:
orphan predicates, ordinary transaction, max_records+1 lookahead and per-table
max_records cap remain exact. At max_records=1000 authority is at most 1000
archives + 1000 hot_chunks + 1000 address_keys. Committed native units are
published before the existing source/urgent boundary; no ordinary scope work
runs after that boundary requests return. The tail does not invoke a second GC
batch. No checkpoint/vacuum or new atomic shield moves into the prefix. The
original scope-loop AST, cursor rotation, pins, floors, continuity and record
accounting are unchanged. Possible newly created orphans are reported unknown
instead of falsely idle. Credit is retirement / __housekeeping__ / records=0 /
actual committed deletion units; no other scope is credited.

### BASE

```python
                    from .solana_maintenance_state import progress as maintenance_progress
                    maintenance_progress(self,scope,'retirement',len(ids)+removed[0]+int(floor_changed),len(ids))
                if not more_here:break
        # Skip no-op housekeeping transactions too. Keep immutable archive files;
        # only unreferenced operational manifests/chunks/dictionary keys retire.
        garbage=[]
        for table,key,sql in (
            ('archives','name','SELECT name FROM archives WHERE name NOT IN (SELECT DISTINCT archive FROM records WHERE archive IS NOT NULL) LIMIT ?'),
            ('hot_chunks','hash','SELECT hash FROM hot_chunks c WHERE NOT EXISTS(SELECT 1 FROM hot_refs r WHERE r.hash=c.hash) LIMIT ?'),
            ('address_keys','id','SELECT id FROM address_keys k WHERE NOT EXISTS(SELECT 1 FROM address_refs r WHERE r.address_id=k.id) LIMIT ?')):
            keys=[r[0] for r in self.db.execute(sql,(max_records+1,))]
            if len(keys)>max_records:progress.remaining.add('gc:'+table)
            if keys:garbage.append((table,key,keys[:max_records]))
        if garbage:
            removed=0
            with self.transaction():
                for table,key,keys in garbage:
```

### M1

```python
                    from .solana_maintenance_state import progress as maintenance_progress
                    maintenance_progress(self,scope,'retirement',len(ids)+removed[0]+int(floor_changed),len(ids))
                if not more_here:break
        # Skip no-op housekeeping transactions too. Keep immutable archive files;
        # only unreferenced operational manifests/chunks/dictionary keys retire.
        garbage=[]
        for table,key,sql in (
            ('archives','name','SELECT name FROM archives WHERE name NOT IN (SELECT DISTINCT archive FROM records WHERE archive IS NOT NULL) LIMIT ?'),
            ('hot_chunks','hash','SELECT hash FROM hot_chunks c WHERE NOT EXISTS(SELECT 1 FROM hot_refs r WHERE r.hash=c.hash) LIMIT ?'),
            ('address_keys','id','SELECT id FROM address_keys k WHERE NOT EXISTS(SELECT 1 FROM address_refs r WHERE r.address_id=k.id) LIMIT ?')):
            keys=[r[0] for r in self.db.execute(sql,(max_records+1,))]
            if len(keys)>max_records:progress.remaining.add('gc:'+table)
            if keys:garbage.append((table,key,keys[:max_records]))
        if garbage:
            removed=0
            with self.transaction():
                for table,key,keys in garbage:
```

### M1/A2

```python
                    from .solana_maintenance_state import progress as maintenance_progress
                    maintenance_progress(self,scope,'retirement',len(ids)+removed[0]+int(floor_changed),len(ids))
                if not more_here:break
        # Skip no-op housekeeping transactions too. Keep immutable archive files;
        # only unreferenced operational manifests/chunks/dictionary keys retire.
        garbage=[]
        for table,key,sql in (
            ('archives','name','SELECT name FROM archives WHERE name NOT IN (SELECT DISTINCT archive FROM records WHERE archive IS NOT NULL) LIMIT ?'),
            ('hot_chunks','hash','SELECT hash FROM hot_chunks c WHERE NOT EXISTS(SELECT 1 FROM hot_refs r WHERE r.hash=c.hash) LIMIT ?'),
            ('address_keys','id','SELECT id FROM address_keys k WHERE NOT EXISTS(SELECT 1 FROM address_refs r WHERE r.address_id=k.id) LIMIT ?')):
            keys=[r[0] for r in self.db.execute(sql,(max_records+1,))]
            if len(keys)>max_records:progress.remaining.add('gc:'+table)
            if keys:garbage.append((table,key,keys[:max_records]))
        if garbage:
            removed=0
            with self.transaction():
                for table,key,keys in garbage:
```

### Integrated result

```python
        from .solana_retention_outcome import RetentionProgress
        self._check()
        progress=self.last_retention_progress=RetentionProgress()
        if not 1 <= max_records <= 1000:raise EvidenceUnavailable('retention_batch_bound')
        archived=self.archive(before_time,max_records=max_records) if archive_first else 0
        if housekeeping_first:
            # Only the admitted turn's sole peer-blocking obligation is promoted.
            # Publish the existing batch's committed outcome before any yield;
            # keep its ordinary SQL interruptibility and the current scope cursor.
            self._retention_housekeeping(max_records,progress)
            should_yield=getattr(self,'_retention_yield_requested',None)
            yield_class=should_yield() if should_yield else None
            if yield_class:
                progress.interrupted=True;progress.yield_reason=yield_class
                return archived
        source_yield_budget=[2]  # existing three separate 256-record transactions
        scopes=self.db.execute('SELECT scope,slot FROM cursors ORDER BY scope').fetchall()
```

### Full exact delta from M1/A2

```diff
diff --git a/meme_machine/solana_evidence_plane.py b/meme_machine/solana_evidence_plane.py
index 34ef169e..207e0df1 100644
--- a/meme_machine/solana_evidence_plane.py
+++ b/meme_machine/solana_evidence_plane.py
@@ -641 +641 @@ class EvidenceWriter:
-    def retain(self, before_time, *, max_records=1000, archive_first=True, checkpoint=True):
+    def retain(self, before_time, *, max_records=1000, archive_first=True, checkpoint=True, housekeeping_first=False):
@@ -652,0 +653,10 @@ class EvidenceWriter:
+        if housekeeping_first:
+            # Only the admitted turn's sole peer-blocking obligation is promoted.
+            # Publish the existing batch's committed outcome before any yield;
+            # keep its ordinary SQL interruptibility and the current scope cursor.
+            self._retention_housekeeping(max_records,progress)
+            should_yield=getattr(self,'_retention_yield_requested',None)
+            yield_class=should_yield() if should_yield else None
+            if yield_class:
+                progress.interrupted=True;progress.yield_reason=yield_class
+                return archived
@@ -727,0 +738,10 @@ class EvidenceWriter:
+        if not housekeeping_first:
+            self._retention_housekeeping(max_records,progress)
+        if checkpoint:self.db.execute('PRAGMA wal_checkpoint(PASSIVE)')
+        self.db.execute('PRAGMA incremental_vacuum(256)')
+        # Scope retirement after a prefix can orphan new operational rows.
+        # They were not examined by that batch; do not claim an idle backlog.
+        progress.complete=not (housekeeping_first and progress.retired_records)
+        return archived
+
+    def _retention_housekeeping(self,max_records,progress):
@@ -747,4 +766,0 @@ class EvidenceWriter:
-        if checkpoint:self.db.execute('PRAGMA wal_checkpoint(PASSIVE)')
-        self.db.execute('PRAGMA incremental_vacuum(256)')
-        progress.complete=True
-        return archived
```

## Q2 and evidence overlap

Only corrected qualification-v2 source and its two v2 workflow files were
selected from ace479836690e65c091407e7da7545ad61952f31. Its publication history
is referenced, not merged. Original plans, schema v3, gate map, observer
contract, fixture identities, trial matrix, material firewall, witness and
71 test identities remain exact. The integrated input manifest is refreshed
for all consumed integrated bytes. The separately disclosed environment-specific
unused websockets console-launcher hash is the only dependency-lock difference;
all importable runtime bytes remain exact. Fresh binding/input/schema/workflow
checks gate this composition. Frozen historical plans and fixtures remain exact.

The static verifier compares the selector against the exact historical patch,
GC and scope-loop AST against the integration base, and completion/cooperative
AST and protected production/test bytes against M1/A2. The 21 focused HK checks
cover boundaries, competing effective deadlines, zero demand, receipt readiness,
rollback, urgent SQL, committed source/urgent return, native deletion bounds,
immutable files, cursor rotation and fresh turn isolation. Three separately
classified checks add actual native old/control versus integrated receipt-74-
shaped feasibility, late committed-prefix lease failure and restart without
duplicate credit. They do not change the 621 or Q2 71 denominators. They assert
restored archive feasibility only, and do not require archive selection.

All runtime production bytes remain the durable reconstruction already reviewed
in the recovery. The new assignment changes integration-only declarations,
execution/report controls and bounded proof source; it adds no production behavior.
