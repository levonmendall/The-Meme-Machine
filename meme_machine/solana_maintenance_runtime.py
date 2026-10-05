"""Single production maintenance authority, executed by the existing SQL owner.

No provider access, policy authority, extra executor, or independent retention
loop lives here. The carrier holds at most one archive future/receipt. The owner
checks readiness *at execution*, after previously queued source/control work.
"""
from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass
import math
import sqlite3
import time

from .solana_evidence_plane import EvidenceUnavailable
from .solana_maintenance_state import (DebtAgeAdapter, MAX_SCOPES,
    PRESERVATION_SECONDS, RESIDENCE_SECONDS, RECOVERY_SOURCE_SECONDS,
    PIPELINE_SLACK_RECORDS)
from .solana_maintenance_arbiter import ClockModel, MaintenanceArbiter, Need, ServiceLeases


@dataclass
class ArchiveFlight:
    """One logical archive operation; mutations occur on the owner, attachment at its quiescent return."""
    future: object = None
    submitted: float | None = None
    pending: tuple | None = None
    prepared: dict | None = None
    generation: str | None = None

    def attach(self, future, submitted, generation):
        if self.future is not None or self.pending is not None or self.prepared is None:
            raise EvidenceUnavailable('maintenance_archive_concurrency')
        self.prepared = None
        self.future, self.submitted, self.generation = future, submitted, generation

    @property
    def idle(self):
        return self.future is None and self.pending is None and self.prepared is None


class MaintenanceRuntime:
    """Owner-affine debt adapter, deadline state, arbiter and bounded telemetry."""
    def __init__(self, state, *, monotonic=None, wall=None, leases=None):
        self.state = state
        self.writer = state.writer
        self.monotonic = monotonic or time.monotonic
        self.wall = wall or time.time
        self.leases = leases or ServiceLeases()
        self.leases.validate()
        self.generation = state.fence.session
        self.adapter = DebtAgeAdapter(self.writer, monotonic=self.monotonic, wall=self.wall)
        now, wall_now = self.monotonic(), self.wall()
        self.clock = ClockModel(wall_now, now, self.leases.clock_error)
        self.arbiter = MaintenanceArbiter(self.generation, self.leases)
        self.ring = deque(maxlen=64)
        self.counters = Counter()
        self.episodes = {}
        self.demand_since = {}
        self.nonrecord_since = {}
        self.failure = None
        self.last_observation = None
        self.last_progress = {}
        self.observation_total = 0.0
        self.execution_total = 0.0
        self.epoch = now
        self._load()
        self._publish()

    def _load(self):
        rows = self.writer.db.execute('SELECT scope,side,source_deadline,wall_started,envelope FROM maintenance_episodes ORDER BY scope,side LIMIT ?', (MAX_SCOPES*2+3,)).fetchall()
        if len(rows) > MAX_SCOPES*2+2:
            raise EvidenceUnavailable('maintenance_episode_bound')
        for scope, side, deadline, started, envelope in rows:
            if side not in ('archive','retirement') or not math.isfinite(deadline) or not math.isfinite(started) or envelope != PIPELINE_SLACK_RECORDS:
                raise EvidenceUnavailable('maintenance_episode_invalid')
            self.episodes[side,scope] = (deadline, started, envelope)
        rows = self.writer.db.execute('SELECT scope,side,wall_started FROM maintenance_nonrecord_demand ORDER BY scope,side LIMIT ?', (MAX_SCOPES+2,)).fetchall()
        if len(rows)>MAX_SCOPES+1:
            raise EvidenceUnavailable('maintenance_nonrecord_demand_bound')
        for scope,side,started in rows:
            if side!='retirement' or not math.isfinite(started) or started<=0 or started>self.clock.wall:
                raise EvidenceUnavailable('maintenance_nonrecord_demand_invalid')
            self.nonrecord_since[side,scope]=started

    def _publish(self):
        # Existing health transaction flushes this rolling explanation. No extra
        # per-turn fsync, evidence body, receipt body, or network logging.
        self.state.storage_metrics['maintenance_arbiter'] = dict(
            revision=1, generation=self.generation, decisions=self.arbiter.sequence,
            retained_events=len(self.ring), event_capacity=self.ring.maxlen,
            counters=dict(self.counters), failure=self.failure,
            observation_total_seconds=self.observation_total,
            execution_total_seconds=self.execution_total,
            max_successful_gap=dict(self.arbiter.max_gap),
            scope_successful_gaps=[dict(side=s,scope=p,seconds=v)
                for (s,p),v in sorted(self.arbiter.max_scope_gap.items())],
            lease=dict(vars(self.leases)), events=list(self.ring))

    def _record(self, row):
        if len(self.ring)==self.ring.maxlen:
            self.counters['evicted_events'] += 1
        self.ring.append(row)
        self.counters[row.get('reason','unknown')] += 1
        self._publish()

    def _episode(self, side, scope, debt, source_now, wall_now):
        key = side,scope
        prior = self.episodes.get(key)
        if debt <= PIPELINE_SLACK_RECORDS:
            if prior is not None:
                with self.writer.transaction():
                    self.writer.db.execute('DELETE FROM maintenance_episodes WHERE side=? AND scope=?',(side,scope))
                self.episodes.pop(key)
            return None
        # A latched episode does not authorize using an absent current frontier.
        # Receipt deletion is harmless; deletion/loss of its durable authority is
        # not. Fail closed without clearing or extending the stored deadline.
        if source_now is None or not math.isfinite(source_now) or source_now > wall_now:
            raise EvidenceUnavailable('maintenance_recovery_source_unavailable')
        if prior is None:
            prior = source_now+RECOVERY_SOURCE_SECONDS, wall_now, PIPELINE_SLACK_RECORDS
            with self.writer.transaction():
                self.writer.db.execute('INSERT INTO maintenance_episodes VALUES(?,?,?,?,?)',
                    (scope,side,*prior))
            self.episodes[key] = prior
        return self.clock.project(prior[0])

    def _nonrecord_service_origin(self, key, now, wall_now):
        """Credit only this maintenance owner's durably committed work.

        A permanently nonempty observation can contain newly generated work
        after the preceding call serviced its backlog. Do not keep attributing
        that work to the first sighting forever, and do not use another scope's
        progress (or archive progress) to renew this owner's obligation.
        Record debt keeps its independent oldest-record safety deadline.
        """
        # Persist first required work, not a fresh observation on each restart.
        # Only positive owner progress can advance it; an observed empty queue
        # resolves it. These writes occur on demand transitions, not every turn.
        started = self.nonrecord_since.get(key)
        if started is None:
            started = wall_now
            with self.writer.transaction():
                self.writer.db.execute('INSERT INTO maintenance_nonrecord_demand VALUES(?,?,?)',
                                       (key[1],key[0],started))
            self.nonrecord_since[key]=started
        since = self.clock.project(started)
        prior = self.last_progress.get(key)
        if prior is not None:
            at = prior[2]
            if type(at) not in (int,float) or not math.isfinite(at):
                raise EvidenceUnavailable('maintenance_progress_clock_invalid')
            completed = self.clock.project(at)
            # project() subtracts clock uncertainty; compare the absolute value
            # too so a future timestamp cannot hide inside that allowance.
            if at > wall_now or completed > now:
                raise EvidenceUnavailable('maintenance_progress_clock_invalid')
            since = max(since, completed)
            self.demand_since[key] = since
        return since

    def _resolve_nonrecord(self,key):
        if key in self.nonrecord_since:
            with self.writer.transaction():
                self.writer.db.execute('DELETE FROM maintenance_nonrecord_demand WHERE side=? AND scope=?',key)
            self.nonrecord_since.pop(key)

    def _demands(self, observation):
        now, wall_now = observation.monotonic, observation.wall
        self.clock.check(wall_now, now, {s.scope:s.source_time for s in observation.scopes})
        self.last_progress = {(r[1],r[0]):r for r in observation.recent_progress}
        needs = []
        for s in observation.scopes:
            for side, debt, oldest, extra in [
                ('archive',s.hot_eligible,s.hot_oldest,0),
                ('retirement',s.retirement_eligible,s.retirement_oldest,s.continuity+int(s.floor_changed))]:
                units = debt+extra
                key = side,s.scope
                if units:
                    since = (self.demand_since.setdefault(key, now) if debt else
                             self._nonrecord_service_origin(key, now, wall_now))
                    safety = self.clock.project(oldest+RESIDENCE_SECONDS) if oldest is not None else since+self.leases.drought
                    if side=='archive' and s.blocked_retirement_oldest is not None:
                        safety = min(safety,self.clock.project(s.blocked_retirement_oldest+RESIDENCE_SECONDS))
                    p = self.last_progress.get(key)
                    if key not in self.arbiter.origin:
                        # A prior operation that preceded current eligibility is
                        # not a service drought. Old active evidence, however,
                        # receives no fresh 45-second gift merely on restart.
                        began = self.clock.project(oldest+PRESERVATION_SECONDS) if oldest is not None else since
                        last = p[4] if debt and p else p[2] if p else None
                        origin = max(began, self.clock.project(last) if last is not None else began)
                        self.arbiter.restore_progress(s.scope,side,min(now,origin),now)
                else:
                    self.demand_since.pop(key,None)
                    self._resolve_nonrecord(key)
                    safety = now+self.leases.drought
                recovery = self._episode(side,s.scope,debt,s.source_time,wall_now)
                needs.append(Need(s.scope,side,units,debt,safety,recovery,max(0,debt-PIPELINE_SLACK_RECORDS)))
        key = 'retirement','__housekeeping__'
        if observation.housekeeping:
            since = self._nonrecord_service_origin(key,now,wall_now)
            needs.append(Need(key[1],key[0],observation.housekeeping,0,
                since+self.leases.drought,None,0))
        else:
            self.demand_since.pop(key,None)
            self._resolve_nonrecord(key)
            needs.append(Need(key[1],key[0],0,0,now+self.leases.drought,None,0))
        return needs

    @contextmanager
    def execution_lease(self, deadline):
        """Cooperative SQL expiry plus mandatory post-operation elapsed check.

        Atomic native retirement slices remain atomic. A blocked OS or atomic
        commit is not claimed preemptible: a late return revokes the lease and
        fails the service; no resulting sample qualifies as a liveness success.
        """
        previous = getattr(self.writer,'_owner_progress_handler',None)
        expired = False
        def checked():
            nonlocal expired
            if expired:return 0  # permit native rollback
            if self.monotonic() >= deadline and not getattr(self.writer,'_retention_atomic',False):
                expired=True
                return 1
            return previous() if previous else 0
        self.writer._owner_progress_handler = checked
        self.writer.db.set_progress_handler(checked,1000)
        try:
            yield
        except sqlite3.OperationalError as exc:
            if expired:
                raise EvidenceUnavailable('maintenance_execution_lease_exceeded') from exc
            raise
        finally:
            self.writer.db.set_progress_handler(previous,1000 if previous else 0)
            self.writer._owner_progress_handler = previous
            if expired:
                self.arbiter.failed = True

    def _native_progress(self, before, needs, side):
        rows = self.writer.db.execute('SELECT scope,side,at,units,record_at,records FROM maintenance_progress ORDER BY scope,side LIMIT ?', (MAX_SCOPES*2+3,)).fetchall()
        if len(rows)>MAX_SCOPES*2+2:
            raise EvidenceUnavailable('maintenance_progress_bound')
        record_required={n.scope for n in needs if n.side==side and n.records}
        progress, records = {},{}
        for row in rows:
            scope,s,_,units,_,count = row
            if s!=side:continue
            old=before.get((s,scope))
            du=units-(old[3] if old else 0);dr=count-(old[5] if old else 0)
            if du<0 or dr<0 or dr>du:
                raise EvidenceUnavailable('maintenance_progress_regressed')
            if dr:records[scope]=dr
            # Housekeeping or floor progress cannot renew a successful record
            # service drought while record retirement is actually needed.
            progress[scope]=dr if scope in record_required else du
        return progress,records

    def _cooperative(self, exc):
        # The owner flag records a prior interrupt, not the cause of every later
        # SQLite error. Require the actual interrupt result as well.
        if isinstance(exc, EvidenceUnavailable):
            return str(exc) == 'evidence_background_yield'
        if not isinstance(exc, sqlite3.OperationalError):
            return False
        code = getattr(exc, 'sqlite_errorcode', None)
        return (getattr(self.writer, '_background_sql_interrupted', False) and
                (code == sqlite3.SQLITE_INTERRUPT or
                 (code is None and str(exc) == 'interrupted')))

    def _complete_decision(self, decision, needs, event, execution_error, execution_deadline):
        # A failed accounting read is terminal fail-closed for this turn. Keep
        # the exact pending identity as a tripwire when its outcome is unknown.
        # Never clear it or credit an uncommitted/invented progress value.
        event['completion'] = 'failed_closed'
        if self.writer.db.in_transaction:
            raise EvidenceUnavailable('maintenance_completion_transaction_open')
        yielded = None
        try:
            progress, records = self._native_progress(self.last_progress, needs, decision.side)
        except BaseException as exc:
            if not self._cooperative(exc):
                raise
            yielded = exc
            event['completion_read_interrupted'] = True
            previous = getattr(self.writer, '_owner_progress_handler', None)
            # Only retry the bounded ledger SELECT (at most 2*MAX_SCOPES+3
            # rows), after native mutation/rollback has ended. Only this read
            # temporarily defers SQL preemption. The unchanged generation and
            # execution deadlines are checked before crediting service.
            self.writer.db.set_progress_handler(None, 0)
            try:
                progress, records = self._native_progress(self.last_progress, needs, decision.side)
            except BaseException as retry_error:
                raise EvidenceUnavailable('maintenance_completion_unavailable') from retry_error
            finally:
                self.writer.db.set_progress_handler(previous, 1000 if previous else 0)
        # Preserve known durable progress even when completion rejects a lease
        # or identity. Its existence does not turn a failed decision into success.
        event.update(durable_progress=progress, durable_records=records)
        if self.state.fence.session != self.generation:
            raise EvidenceUnavailable('maintenance_generation_changed')
        now = self.monotonic()
        if now >= execution_deadline:
            raise EvidenceUnavailable('maintenance_execution_lease_exceeded')
        try:
            self.arbiter.complete(decision, now, progress, record_progress=records)
        except BaseException as completion_error:
            # complete() has no cooperative SQL boundary. A failure here must
            # not reopen admission with the original decision still pending.
            if self._cooperative(completion_error):
                raise EvidenceUnavailable('maintenance_completion_unavailable') from completion_error
            raise
        event['completion'] = 'completed'
        # A recovered reporting interrupt still yields to its accepted waiter.
        # It must not replace a fatal error from the native operation itself.
        if yielded is not None and execution_error is None:
            raise yielded

    def _housekeeping_first(self,decision,observation,needs,ready,flight):
        """Use only this already-admitted turn's fresh effective deadlines."""
        if (decision is None or decision is not self.arbiter.pending or
                decision.side!='retirement' or observation is not self.last_observation or
                observation.generation!=self.generation or
                self.state.fence.session!=self.generation or
                flight.generation!=self.generation or flight.pending is None or
                not ready['archive'] or observation.housekeeping<=0):
            return False
        active=[n for n in needs if n.side=='retirement' and n.units]
        housekeeping=[n for n in active if n.scope=='__housekeeping__']
        if len(housekeeping)!=1:
            return False
        def effective(n):
            # Exactly choose()'s safety, successful-service drought and, when
            # active, recovery minimum. Origins were established by that choice.
            deadline=min(n.safety_deadline,
                         self.arbiter.origin[n.side,n.scope]+self.leases.drought)
            if n.recovery_excess:
                deadline=min(deadline,n.recovery_deadline)
            return deadline
        now=decision.started
        peer_window=now+2*self.leases.execution+self.leases.owner
        return (now+self.leases.execution<effective(housekeeping[0])<=peer_window and
                all(effective(n)>peer_window for n in active
                    if n.scope!='__housekeeping__'))

    def _newly_eligible_old_evidence(self,current,previous):
        """Distinguish released/backfilled old data from unserviced old debt.

        Immutable market times remain unchanged. A previously healthy scope can
        gain older eligible data when repair completes or a lifecycle releases
        its protection. That transition needs actual bounded cleanup, rather
        than killing every lane. Existing service/recovery droughts still fail.
        """
        if previous is None or previous.generation!=current.generation:return False
        now=current.monotonic
        if (any(at+self.leases.drought<=now for at in self.arbiter.origin.values()) or
                any(self.clock.project(row[0])<=now for row in self.episodes.values())):
            return False
        prior={s.scope:s for s in previous.scopes};found=False
        for scope in current.scopes:
            old=prior.get(scope.scope)
            for field in ('hot_oldest','retirement_oldest','blocked_retirement_oldest'):
                at=getattr(scope,field)
                if at is None or self.clock.project(at+RESIDENCE_SECONDS)>now:continue
                before=getattr(old,field) if old is not None else None
                if before is not None and before<=at:return False
                found=True
        return found

    def cold_completed(self,observation,flight=None):
        """Resume only after real overdue cleanup, crediting committed work."""
        if (flight is not None and not flight.idle or
                observation.generation!=self.generation or observation.housekeeping or
                any(at is not None and self.clock.project(at+RESIDENCE_SECONDS)<=observation.monotonic
                    for s in observation.scopes for at in
                    (s.hot_oldest,s.retirement_oldest,s.blocked_retirement_oldest))):
            raise EvidenceUnavailable('maintenance_startup_recovery_incomplete')
        self.last_observation=observation
        self.arbiter.origin.pop(('archive','__archive_receipt__'),None)
        needs=self._demands(observation)
        before=getattr(self,'cold_progress_before',{})
        for need in needs:
            key=need.side,need.scope;row=self.last_progress.get(key)
            prior=before.get(key,(0,0))
            # Cumulative native counters must show new committed work of the
            # right kind. Observation, eligibility or a young row gives no credit.
            if row and (row[5]>prior[1] if need.records else row[3]>prior[0]):
                at=row[4] if need.records else row[2]
                credited=self.clock.project(at)
                if credited>observation.monotonic:
                    raise EvidenceUnavailable('maintenance_progress_clock_invalid')
                self.arbiter.origin[key]=max(self.arbiter.origin.get(key,credited),credited)
        self.cold_progress_before={}
        for need in needs:
            if not need.units:self.arbiter.origin.pop((need.side,need.scope),None)
        # The next ordinary turn owns admission of remaining young work. Do
        # not reserve a decision here and strand it without its native execution.


    def turn(self, flight, submitted):
        """Exactly one fresh owner-entry decision and at most one native side."""
        self.writer._check()
        start=self.monotonic();decision=None;needs=();event=None
        if self.failure:
            raise EvidenceUnavailable('maintenance_admission_revoked')
        try:
            if not math.isfinite(submitted) or submitted>start or start-submitted>self.leases.owner:
                raise EvidenceUnavailable('maintenance_owner_lease_exceeded')
            if self.state.fence.session!=self.generation:
                raise EvidenceUnavailable('maintenance_generation_changed')
            if flight.generation is not None and flight.generation!=self.generation:
                raise EvidenceUnavailable('maintenance_receipt_generation_changed')
            if flight.future is not None:
                if flight.future.done():
                    flight.pending=flight.future.result()
                    flight.future=None
                    if not flight.pending[0]:flight.pending=None
                elif start-flight.submitted>=self.leases.worker:
                    raise EvidenceUnavailable('maintenance_archive_worker_lease_exceeded')
            with self.execution_lease(start+self.leases.execution):
                observation=self.adapter.observe(self.generation)
                self.observation_total += observation.elapsed
                previous=self.last_observation
                self.last_observation=observation
                if self._newly_eligible_old_evidence(observation,previous):
                    self.cold_progress_before={(r[1],r[0]):(r[3],r[5]) for r in observation.recent_progress}
                    self._record(dict(reason='cold_recovery_required',at=self.monotonic(),
                        generation=self.generation,selected=None))
                    return dict(side=None,archive_pressure=True,retirement_pressure=True,
                        cold_recovery_required=True)
                needs=self._demands(observation)
                now=self.monotonic()
                # A durable final slice can commit and then yield before its
                # caller acknowledges the receipt. Hot debt is then zero, but
                # the original bounded receipt still requires an idempotent
                # completion turn. This is observed carrier work, not fabricated
                # record debt/progress or a second archive publication.
                receipt_key=('archive','__archive_receipt__')
                if flight.pending is not None:
                    if flight.submitted is None or not math.isfinite(flight.submitted) or flight.submitted>now:
                        raise EvidenceUnavailable('maintenance_receipt_clock_invalid')
                    needs.append(Need(receipt_key[1],receipt_key[0],1,0,
                        flight.submitted+self.leases.worker+self.leases.drought,None,0))
                else:
                    self.arbiter.origin.pop(receipt_key,None)
                # Preparation initiation is an archive turn without progress.
                # Waiting on a worker is not READY and never renews drought.
                ready=dict(archive=flight.pending is not None or flight.idle,
                           retirement=True)
                decision=self.arbiter.choose(generation=self.state.fence.session,
                    as_of=observation.monotonic,now=now,needs=needs,ready=ready)
                event=dict(sequence=decision.sequence if decision else None,
                    generation=self.generation,selected=decision.side if decision else None,
                    reason=decision.reason if decision else 'no_ready_required_work',
                    at=now,owner_delay=start-submitted,
                    scope_state=[dict(scope=s.scope,hot=s.hot_eligible,hot_age=None if s.hot_oldest is None else observation.wall-s.hot_oldest,
                        archived_pending=s.archived_pending,retirement=s.retirement_eligible,
                        retirement_age=None if s.retirement_oldest is None else observation.wall-s.retirement_oldest,
                        pins=s.pins,gaps=s.gaps,floor=s.floor,continuity=s.continuity,
                        floor_changed=s.floor_changed,account_floor=s.account_floor)
                        for s in observation.scopes],housekeeping=observation.housekeeping,
                    deadlines=dict(decision.deadline_by_side) if decision else {},
                    reservations=dict(vars(self.leases)),ready=ready,
                    receipt_pending=flight.pending is not None)
                result=dict(snapshot=None,side=decision.side if decision else None,
                    archive_pressure=any(n.side=='archive' and n.units for n in needs),
                    retirement_pressure=any(n.side=='retirement' and n.units for n in needs))
                if decision is not None:
                    execution_error = None
                    try:
                        if decision.side=='archive':
                            if flight.pending is None:
                                result['snapshot']=self.state.archive_plan()
                                flight.prepared=result['snapshot']
                                flight.generation=self.generation
                            else:
                                plan,receipt=flight.pending
                                remaining,snapshot=self.state.archive_commit_slice_and_plan(plan,receipt)
                                if remaining:
                                    flight.pending=(remaining,receipt)
                                else:
                                    flight.pending=None;flight.prepared=snapshot
                                    # This exact receipt was acknowledged. A
                                    # successor must not inherit its completed
                                    # administrative obligation; record-service
                                    # clocks still advance only from the ledger.
                                    self.arbiter.origin.pop(receipt_key,None)
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
            if end-start>self.leases.execution:
                raise EvidenceUnavailable('maintenance_execution_lease_exceeded')
            event['execution']=end-start
            self.execution_total += end-start
            self._record(event)
            return result
        except BaseException as exc:
            # Cooperative priority yields preserve an already durable receipt.
            # They are not successful service and do not invalidate native work.
            cooperative=self._cooperative(exc)
            if not cooperative and type(exc) is EvidenceUnavailable and needs:
                # Fixed numeric diagnostics survive worker death without raw
                # provider text, payloads or another state/authority store.
                now=self.monotonic()
                active=[n for n in needs if n.units]
                if active:
                    def deadline(n):
                        return min(n.safety_deadline,
                            self.arbiter.origin.get((n.side,n.scope),now)+self.leases.drought,
                            n.recovery_deadline if n.recovery_excess and n.recovery_deadline is not None else math.inf)
                    need=min(active,key=deadline)
                    scope=next((s for s in self.last_observation.scopes if s.scope==need.scope),None)
                    exc.maintenance_failure=dict(side=need.side,units=need.units,
                        records=need.records,deadline_seconds=deadline(need)-now,
                        safety_seconds=need.safety_deadline-now,
                        drought_seconds=self.arbiter.origin.get((need.side,need.scope),now)+self.leases.drought-now,
                        recovery_seconds=None if need.recovery_deadline is None else need.recovery_deadline-now,
                        pins=None if scope is None else scope.pins,gaps=None if scope is None else scope.gaps,
                        vm_steps=self.last_observation.vm_steps)
            if not cooperative:
                self.failure=type(exc).__name__+':'+str(exc)[:120]
                self.arbiter.failed=True
            if event is None:
                event=dict(sequence=None,generation=self.generation,selected=None,
                    at=start,owner_delay=start-submitted,reason='cooperative_yield' if cooperative else 'fail_closed')
            else:event['reason']='cooperative_yield' if cooperative else 'fail_closed'
            event.update(execution=self.monotonic()-start,error=type(exc).__name__+':'+str(exc)[:120])
            if decision is not None:
                event['completion_pending'] = self.arbiter.pending is decision
            self._record(event)
            if not cooperative and isinstance(exc, sqlite3.OperationalError):
                # PriorityOwner also sees the earlier interrupt. Preserve this
                # distinct storage failure instead of letting it become a yield.
                raise EvidenceUnavailable('maintenance_storage_failure') from exc
            if cooperative and not isinstance(exc,EvidenceUnavailable):
                raise EvidenceUnavailable('evidence_background_yield') from exc
            raise
