"""Bounded, opt-in observations of existing native SQLite COMMITs.

These are row-publication receipts, not a source census, economic arrival rate,
canonical coverage proof, source FULL/ACK or authority to operate. No SQL,
provider work, callbacks or persistent measurement writer is introduced.
"""
import hashlib
import os
import threading
import time


STAGES = ('history_event_rows', 'history_reference_rows',
          'qualified_decision_rows', 'refused_decision_rows',
          'pons_generation_dispositions', 'pons_candidate_consumptions')
MAX_RECORDS = 128
MAX_DEPTH = 16
MAX_STORES = 16


class NativeCommitMeasurement:
    def __init__(self, binding):
        self.binding = binding
        self.pid = os.getpid()
        self.lock = threading.Lock()
        self.lost = threading.Event()
        self.counts = dict.fromkeys(STAGES, 0)
        self.transactions = 0
        self.digest = bytes(32)
        self.last_commit_monotonic_ns = None
        self.last_commit_wall_ns = None
        self.stores = set()
        self.next_store = 0

    def attach(self, kind):
        if kind not in ('candidate_history', 'pons_plane'):
            self.lost.set()
            return None
        if not self.lock.acquire(False):
            self.lost.set()
            return None
        try:
            if os.getpid() != self.pid or len(self.stores) >= MAX_STORES:
                self.lost.set()
                return None
            self.next_store += 1
            observer = _Store(self, kind, self.next_store)
            self.stores.add(observer)
            return observer
        except Exception:
            self.lost.set()
            return None
        finally:
            self.lock.release()

    def snapshot(self):
        # The binding describes authenticated transport provenance, never a
        # canonical source generation or a complete economic population.
        value = dict(schema='native-commit-observations-v1', binding=dict(self.binding),
            financial_authority=False, authoritative_readiness=False,
            source_economic_events=None, source_publication_obligations=None,
            source_verified_acks=None, unique_candidate_generations=None,
            all_consumer_completion=None, economic_lambda=None, economic_mu=None,
            economic_backlog=None, cohort_closure='UNKNOWN',
            pons_pool_universe_closure='UNKNOWN', persistence='PROCESS_LOCAL_ONLY')
        if not self.lock.acquire(False):
            self.lost.set()
            value.update(status='UNKNOWN', measurement_loss=True)
            return value
        try:
            if os.getpid() != self.pid:
                self.lost.set()
            value.update(status='UNKNOWN' if self.lost.is_set() else 'COMMIT_STAGE_ONLY',
                measurement_loss=self.lost.is_set(), committed_row_counts=dict(self.counts),
                observed_transactions=self.transactions, commit_chain_hash=self.digest.hex(),
                last_commit_monotonic_ns=self.last_commit_monotonic_ns,
                last_commit_wall_ns=self.last_commit_wall_ns, active_stores=len(self.stores))
            return value
        finally:
            self.lock.release()


class _Store:
    """Only an owned native transaction may supply a row and commit outcome."""
    def __init__(self, collector, kind, identity):
        self.collector, self.kind, self.identity = collector, kind, identity
        self.frames = []
        self.disabled = False
        self.closed = False

    def fail(self):
        self.collector.lost.set()
        self.disabled = True
        self.frames.clear()

    def begin(self, *, nested=False):
        try:
            if self.disabled or self.closed:
                return None
            # A SAVEPOINT inside an externally opened transaction cannot prove
            # outer FULL. Do not publish when its helper returns.
            if (os.getpid() != self.collector.pid or len(self.frames) >= MAX_DEPTH
                    or bool(self.frames) != nested):
                self.fail()
                return None
            frame = [dict.fromkeys(STAGES, 0), bytes(32), 0]
            self.frames.append(frame)
            return frame
        except Exception:
            self.fail()
            return None

    def record(self, stage, *fields):
        try:
            if self.disabled or self.closed:
                return
            if not self.frames or stage not in STAGES or len(fields) > 8:
                self.fail()
                return
            frame = self.frames[-1]
            # Fixed allocation and hashing bounds; no payload/body serialization.
            if sum(f[2] for f in self.frames) >= MAX_RECORDS:
                self.fail()
                return
            chunks = [stage.encode('ascii')]
            for field in fields:
                if type(field) is str and len(field) <= 256:
                    raw = field.encode('utf-8')
                elif type(field) is int and -(2**63) <= field < 2**63:
                    raw = str(field).encode('ascii')
                elif field is None:
                    raw = b'null'
                else:
                    self.fail()
                    return
                if len(raw) > 512:
                    self.fail()
                    return
                chunks.append(len(raw).to_bytes(2, 'big') + raw)
            frame[1] = hashlib.sha256(frame[1] + b'\0'.join(chunks)).digest()
            frame[0][stage] += 1
            frame[2] += 1
        except Exception:
            self.fail()

    def finish(self, frame, *, committed, uncertain=False):
        try:
            if self.disabled or self.closed:
                return
            if uncertain or not self.frames or self.frames[-1] is not frame:
                self.fail()
                return
            self.frames.pop()
            if not committed or not frame[2]:
                return
            if self.frames:
                parent = self.frames[-1]
                for stage in STAGES:
                    parent[0][stage] += frame[0][stage]
                parent[1] = hashlib.sha256(parent[1] + frame[1]).digest()
                parent[2] += frame[2]
                return
            # Called only after the native outer COMMIT has returned. The
            # nonblocking reducer never waits for another SQLite owner.
            mono, wall = time.monotonic_ns(), time.time_ns()
            collector = self.collector
            if not collector.lock.acquire(False):
                self.fail()
                return
            try:
                if os.getpid() != collector.pid:
                    self.fail()
                    return
                for stage in STAGES:
                    collector.counts[stage] += frame[0][stage]
                collector.transactions += 1
                collector.digest = hashlib.sha256(collector.digest + self.kind.encode('ascii')
                    + self.identity.to_bytes(8, 'big') + frame[1]
                    + mono.to_bytes(8, 'big')).digest()
                collector.last_commit_monotonic_ns = mono
                collector.last_commit_wall_ns = wall
            finally:
                collector.lock.release()
        except Exception:
            self.fail()

    def close(self):
        if self.closed:
            return
        if self.frames:
            self.fail()
        self.closed = True
        if not self.collector.lock.acquire(False):
            self.fail()
            return
        try:
            self.collector.stores.discard(self)
        finally:
            self.collector.lock.release()
