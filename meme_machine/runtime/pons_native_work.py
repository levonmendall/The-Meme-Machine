"""Observed turn inventories distinct from actually issued native requests.

Original due eligibility does not issue an evaluation for every candidate. The
unchanged native selector owns issuance; only a matching real History save after
outer COMMIT settles it. This module has no SQL/provider/financial authority.
"""
from contextlib import contextmanager
import os
import threading

from .journal import digest
from .native_work_cohort import NativeWorkCohorts,project_native_work

MAX_ROWS=32768


class PonsNativeWork:
    def __init__(self,owner):
        from .pons_economic_cohort import PonsEconomicCohorts
        if type(owner) is not PonsEconomicCohorts:raise ValueError('pons_native_work_owner_required')
        owner.require_owner()
        if owner.native_owner is None:raise ValueError('pons_native_work_private_owner_required')
        self.owner=owner;self.pid=os.getpid();self.lock=threading.Lock()
        self.sequence=0;self.inventory=None;self.loss=None
        binding=dict(native_owner=owner.native_owner.identity_sha256,
            provider_domain=owner.source,regime='pons_survivor',
            canonical_source_generation='UNESTABLISHED',boot_prefix='UNESTABLISHED')
        self.evaluations=NativeWorkCohorts(binding,'NATIVE_EVALUATION')

    def unavailable(self,reason='NATIVE_BOUNDARY_UNAVAILABLE'):
        self.loss=reason
        self.evaluations.unavailable(reason)

    def _apply(self,function):
        if self.loss:return
        if not self.lock.acquire(False):self.unavailable('CONTENTION');return
        try:
            self.owner.require_owner()
            if self.pid!=os.getpid():raise ValueError('owner')
            return function()
        except Exception:self.unavailable()
        finally:self.lock.release()

    def survivor_inputs(self,history):
        def begin():
            from meme_machine.lanes.pons.pons_history import PonsHistory
            if type(history) is not PonsHistory or history.economic_cohorts is not self.owner:
                raise ValueError('history_owner')
            if history.db.in_transaction:raise ValueError('foreign_transaction')
            if self.inventory is not None and not self.inventory.finished:
                raise ValueError('incomplete_previous_iterator')
            self.sequence+=1
            frontier=digest(self.owner.membership.snapshot())
            frame=_SurvivorInputs(self,history,self.sequence,frontier)
            self.inventory=frame;return frame
        return self._apply(begin)

    def decision(self,row,decision,state,request):
        def selected():
            if type(request) is not _EvaluationRequest or request.owner is not self:
                raise ValueError('native_request')
            if row.get('position') or row.get('complete') is not True or row.get('recovery'):
                return None
            # The caller is the original native qualification publisher. Its
            # actual decision/history body and native canonical state are bound
            # after its original save, never a supplied readiness flag.
            if (row['id']!=request.candidate or row.get('qualification_attempt')!=request.attempt
                    or digest(row['graduation'])!=request.graduation):
                raise ValueError('native_request_generation')
            return _DecisionCommit(self,request,digest(decision),state['block'],state['block_hash'])
        return self._apply(selected)

    def snapshot(self):
        try:self.owner.require_owner()
        except Exception:self.unavailable()
        if not self.lock.acquire(False):
            return dict(state='UNKNOWN',reason='CONTENTION',funding_authority=False)
        try:return dict(state='UNKNOWN' if self.loss else 'MEASURING',
            contract='COMPLETE_TURN_INVENTORY_DISTINCT_FROM_ACTUALLY_ISSUED_REQUESTS',
            native_owner_identity_sha256=self.owner.native_owner.identity_sha256,
            latest_turn=None if self.inventory is None else self.inventory.summary(),
            inventory_semantics='LATEST_SQL_EOF_NOT_SEALED_BOOT_OR_CONTINUOUS_SOURCE_CENSUS',
            restored_prefix_closure='UNESTABLISHED',configured_source_closure='UNESTABLISHED',
            current_consumer_closure='UNESTABLISHED',survivor_consumer_closure='UNESTABLISHED',
            held_protection_closure='UNESTABLISHED',full_market_rate='UNKNOWN',
            readiness_authority=False,funding_authority=False,
            issued_evaluations=project_native_work(self.evaluations.snapshot()))
        finally:self.lock.release()


class _SurvivorInputs:
    def __init__(self,owner,history,sequence,frontier):
        self.owner=owner;self.history=history;self.frontier=frontier
        self.sequence=sequence;self.rows={};self.finished=False;self.due=None
        self.issued=set();self.retired=set();self.not_due=set();self.history_selected=set()
        self.population_hash=None;self.held=0;self.admit=None

    @staticmethod
    def key(row,body_hash):
        if type(row['id']) is not str or not 0<len(row['id'])<=256:
            raise ValueError('identity_bound')
        return digest(['pons_survivor',row['id'],row['graduation'],body_hash]),body_hash

    def record(self,row,body_hash):
        def capture():
            if row.get('position'):self.held+=1;return
            if row['state']=='retired':return
            if len(self.rows)>=MAX_ROWS or row['id'] in self.rows:
                self.owner.unavailable('BOUND');return
            self.rows[row['id']]=(self.key(row,body_hash),digest(row['graduation']))
        self.owner._apply(capture)

    def finish(self,independent_keys):
        def complete():
            if self.finished:raise ValueError('duplicate_eof')
            if len(independent_keys)>MAX_ROWS:self.owner.unavailable('BOUND');return
            actual=tuple(sorted(value[0] for value in self.rows.values()))
            if actual!=tuple(sorted(independent_keys)):raise ValueError('census')
            self.population_hash=digest(actual);self.finished=True
        self.owner._apply(complete)

    def _members(self,rows):
        result=set()
        for row in rows:
            if (row['id'] in result or row['id'] not in self.rows
                    or digest(row['graduation'])!=self.rows[row['id']][1]):raise ValueError('membership')
            result.add(row['id'])
        return result

    def filtered(self,row,*,retired=False):
        def observed():
            identity=self._members([row]).pop()
            (self.retired if retired else self.not_due).add(identity)
        self.owner._apply(observed)

    def eligibility(self,rows,*,admit):
        def complete():
            if not self.finished or self.due is not None or type(admit) is not bool:
                raise ValueError('due_census')
            self.due=self._members(rows) if admit else set();self.admit=admit
        self.owner._apply(complete)

    def history_requests(self,rows):
        def observed():self.history_selected.update(self._members(rows))
        self.owner._apply(observed)

    def request(self,row):
        def issued():
            attempt=row.get('qualification_attempt')
            if (self.due is None or row['id'] not in self.due or row['id'] in self.issued
                    or type(attempt) is not int or attempt<1):raise ValueError('native_request')
            self._members([row])
            request=_EvaluationRequest(self.owner,row,attempt,self.frontier)
            self.owner.evaluations.begin(request.cid,self.frontier)
            self.owner.evaluations.expect(request.cid,[request.key])
            self.owner.evaluations.seal_expected(request.cid,1,
                digest((request.key,)),digest(['native_qualification_turn_and_request',request.key]))
            self.issued.add(row['id']);return request
        return self.owner._apply(issued)

    def summary(self):
        due=self.due
        return dict(sequence=self.sequence,sql_eof=self.finished,input_count=len(self.rows),
            input_sha256=self.population_hash,frontier_sha256=self.frontier,
            held_rows_excluded=self.held,admission_enabled=self.admit,
            eligible_count=None if due is None else len(due),
            eligible_sha256=None if due is None else digest(tuple(sorted(self.rows[key][0] for key in due))),
            policy_retired=len(self.retired),native_not_due=len(self.not_due),
            actual_history_requests=len(self.history_selected),actual_evaluation_requests=len(self.issued),
            eligible_unselected=None if due is None else len(due-self.issued),
            input_disposition_contract='ELIGIBILITY_AND_DEFERRAL_NOT_QUALIFICATION_OR_COMPLETION')


class _EvaluationRequest:
    def __init__(self,owner,row,attempt,frontier):
        self.owner=owner;self.candidate=row['id'];self.attempt=attempt
        self.graduation=digest(row['graduation'])
        body_hash=digest(row)
        self.key=(digest(['pons_survivor_issued_evaluation',owner.owner.native_owner.identity_sha256,
            self.candidate,attempt,body_hash]),body_hash)
        self.cid=digest(['issued_native_request',self.key,frontier])


class _DecisionCommit:
    def __init__(self,owner,request,decision,block,block_hash):
        self.owner=owner;self.request=request
        self.candidate=request.candidate;self.graduation=request.graduation
        self.decision_hash=decision;self.block=block;self.block_hash=block_hash;self.saved=None

    def capture(self,row):
        if (row['id']!=self.candidate or digest(row['graduation'])!=self.graduation
                or digest(row.get('decision'))!=self.decision_hash
                or row.get('qualification_attempt')!=self.request.attempt
                or row.get('block')!=self.block or row.get('block_hash')!=self.block_hash):
            self.owner.unavailable();return
        self.saved=digest(row)

    def committed(self):
        def observed():
            if self.saved is None:raise ValueError('missing_native_save')
            # Only the exact original issued qualification-attempt generation
            # earns credit. A later turn cannot settle this request by height.
            self.owner.evaluations.observe(self.request.cid,
                [(*self.request.key,'DECISION_COMMITTED',self.saved,None)])
        self.owner._apply(observed)


@contextmanager
def survivor_inputs(history,work):
    frame=None if work is None else work.survivor_inputs(history)
    previous=getattr(history,'_native_work_rows',None)
    history._native_work_rows=frame
    try:yield frame
    finally:history._native_work_rows=previous


def work_for(runtime):
    owner=getattr(runtime,'economic_cohorts',None)
    value=None if owner is None else getattr(owner,'native_work',None)
    return value if type(value) is PonsNativeWork else None


@contextmanager
def qualification_save(history,work,row,decision,state,request):
    stage=None if work is None or request is None else work.decision(row,decision,state,request)
    previous=getattr(history,'_native_work_save',None);history._native_work_save=stage
    try:yield
    finally:history._native_work_save=previous


def saved(history,row,*,was_transaction):
    stage=getattr(history,'_native_work_save',None)
    if type(stage) is not _DecisionCommit:return
    try:
        stage.capture(row)
        if was_transaction:
            from .pons_source_membership import history_stage
            history_stage(history,stage)
        elif not history.db.in_transaction:stage.committed()
        else:stage.owner.unavailable('TRANSACTION_FAILED')
    except Exception:stage.owner.unavailable()


def rows_frame(history):
    value=getattr(history,'_native_work_rows',None)
    return value if type(value) is _SurvivorInputs and value.history is history else None


def rollback(frame):
    for stage,_,_,_ in frame:
        if type(stage) is _DecisionCommit:stage.owner.unavailable('TRANSACTION_FAILED')
