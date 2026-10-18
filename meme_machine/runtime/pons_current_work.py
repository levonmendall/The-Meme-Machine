"""Actual Current submissions and native commit-stage returns, never an ACK.

Only the original producer call sites invoke these fixed typed hooks. Existing
native APIs cannot nest SQL transactions and return after their outer COMMIT.
No provider call/query, authority, replay relabeling or strategy decision lives
here. Source/boot/held closure is deliberately a separate contract.
"""
from concurrent.futures import Future
import os
import threading

from .journal import canonical,digest
from .native_work_cohort import NativeWorkCohorts,project_native_work

MAX_ROWS=32768
STAGES=('NATIVE_PREPARATION','NATIVE_EVALUATION','NATIVE_WORK_DISPOSITION')


def _key(row):
    if (type(row['id']) is not str or not 0<len(row['id'])<=256
            or row['lane']!='pons' or type(row['generation']) is not int or row['generation']<1):
        raise ValueError('native_current_identity')
    input_hash=digest([row['desired'],row['interpretation'],row['payload'],
        row['latest_id'],row['ordering'],row['observed'],row['deadline']])
    return digest(['pons_current',row['id'],row['generation'],row['desired'],row['interpretation']]),input_hash


class PonsCurrentWork:
    def __init__(self,owner):
        from .pons_economic_cohort import PonsEconomicCohorts
        if type(owner) is not PonsEconomicCohorts or owner.native_owner is None:
            raise ValueError('pons_current_work_owner_required')
        owner.require_owner();self.owner=owner;self.pid=os.getpid();self.lock=threading.Lock()
        self.loss=None;self.latest=None;self.requests={};self.generations={};self.sequence=0
        binding=dict(native_owner=owner.native_owner.identity_sha256,
            provider_domain=owner.source,regime='pons_current',
            canonical_source_generation='UNESTABLISHED',boot_prefix='UNESTABLISHED')
        self.stages={stage:NativeWorkCohorts(binding,stage) for stage in STAGES}

    def unavailable(self,reason='NATIVE_BOUNDARY_UNAVAILABLE'):
        self.loss=reason
        for stage in self.stages.values():stage.unavailable(reason)

    def _apply(self,function):
        if self.loss:return
        if not self.lock.acquire(False):self.unavailable('CONTENTION');return
        try:
            self.owner.require_owner()
            if self.pid!=os.getpid():raise ValueError('owner')
            return function()
        except Exception:self.unavailable()
        finally:self.lock.release()

    def inventory(self,broker,rows):
        def observed():
            if broker.plane.economic_cohorts is not self.owner or len(rows)>MAX_ROWS:
                raise ValueError('inventory_owner_or_bound')
            expected={}
            for row in rows:
                if (row['pending']!=1 or row['interpretation']!=canonical(broker.policy)
                        or row['id'] in expected):raise ValueError('native_pending_query')
                expected[row['id']]=_key(row)
            self.sequence+=1
            self.latest=(expected,digest(tuple(sorted(expected.values()))),
                digest(self.owner.membership.snapshot()),self.sequence)
        self._apply(observed)

    def issued(self,broker,scheduled,future):
        def observed():
            from .robinhood.pons import Broker
            if (type(broker) is not Broker or not isinstance(future,Future)
                    or broker.plane.economic_cohorts is not self.owner or self.latest is None
                    or broker.plane.db.in_transaction):raise ValueError('native_submission')
            row=scheduled['work'];key=_key(row);claim=row['claim']
            if (row['owner']!=broker.plane.owner or type(claim) is not str or len(claim)!=32
                    or any(c not in '0123456789abcdef' for c in claim)
                    or self.latest[0].get(row['id'])!=key or row['pending']!=1
                    or row['interpretation']!=canonical(broker.policy)):
                raise ValueError('native_submission_identity')
            identity=(row['id'],row['generation'],claim)
            if identity in self.requests:return self.requests[identity]
            if len(self.requests)>=MAX_ROWS:raise ValueError('request_bound')
            pair=(row['id'],row['generation'])
            if pair in self.generations:raise ValueError('repeated_generation_request')
            request=_Request(self,identity,key,self.latest[2]);self.requests[identity]=request
            self.generations[pair]=request
            for stage in self.stages.values():
                stage.begin(request.cid,request.frontier);stage.expect(request.cid,[key])
                stage.seal_expected(request.cid,1,digest((key,)),
                    digest(['original_hydration_submission',identity,key]))
            return request
        return self._apply(observed)

    def _request(self,scheduled):
        row=scheduled['work']
        return self.requests.get((row['id'],row['generation'],row['claim']))

    def prepared(self,scheduled,value):
        def observed():
            request=self._request(scheduled)
            if request is None:return
            if _key(scheduled['work'])!=request.key:raise ValueError('request_input')
            request.prepared=digest(value);request.vector=digest(value['vector'])
            request.vector_core=digest({key:item for key,item in value['vector'].items()
                if key!='wallet_convergence'})
            self.stages['NATIVE_PREPARATION'].observe(request.cid,
                [(*request.key,'HISTORY_COMMITTED',request.prepared,None)])
        self._apply(observed)

    def wallet_overlay(self,request,vector,overlay):
        def observed():
            if (type(request) is not _Request or request.owner is not self
                    or request.vector_core is None or vector.get('wallet_convergence')!=overlay
                    or digest({key:item for key,item in vector.items() if key!='wallet_convergence'})
                        !=request.vector_core):raise ValueError('postdecision_wallet_overlay')
            # The original helper changes only this postdecision reporting
            # field. Preserve exact whole-vector equality at qualification.
            request.vector=digest(vector)
        self._apply(observed)

    def decision(self,request,state):
        def observed():
            if type(request) is not _Request or request.owner is not self:raise ValueError('request')
            if request.prepared is None:raise ValueError('missing_prepared_commit')
            request.decision=state
        self._apply(observed)

    def qualification(self,request,body):
        def observed():
            if type(request) is not _Request or request.owner is not self:raise ValueError('request')
            candidate,generation,_=request.identity
            if (body['candidate']!=candidate or body['generation']!=generation
                    or body['phase']!='qualification' or request.decision is None):
                raise ValueError('qualification_generation')
            vector=dict(body['decision']);vector.pop('reentry_explanation',None)
            if digest(vector)!=request.vector:raise ValueError('qualification_body')
            complete=body['category'] in ('QUALIFIED','STRATEGY_REJECT','STRUCTURAL_INELIGIBLE',
                'EXPIRED_BY_STRATEGY_HORIZON')
            expected=('qualified' if body['category']=='QUALIFIED' else
                'strategy_rejected' if body['category']=='STRATEGY_REJECT' else body['category'].lower())
            if request.decision!=expected:raise ValueError('native_decision_category')
            request.qualification=digest(body) if complete else None
            self.stages['NATIVE_EVALUATION'].observe(request.cid,
                [(*request.key,'DECISION_COMMITTED' if complete else 'INCOMPLETE',digest(body),None)])
        self._apply(observed)

    def checkpoint(self,result,cursor,phase):
        def observed():
            rows=result.get('rows')
            if phase!='candidate_consumed' or not rows:return
            last=rows[-1]
            request=self.generations.get((last.get('candidate_identity'),last.get('candidate_generation')))
            if request is None or request.qualification is None:return
            if digest(last.get('vector'))!=request.vector:raise ValueError('checkpoint_decision_body')
            body=canonical(last)
            if len(body.encode())>65536:raise ValueError('checkpoint_row_bound')
            request.checkpoint=digest([request.identity,cursor,phase,digest(last)])
        self._apply(observed)

    def consumed(self,scheduled):
        def observed():
            request=self._request(scheduled)
            if request is None:return
            if request.qualification is None or request.checkpoint is None:return
            self.stages['NATIVE_WORK_DISPOSITION'].observe(request.cid,
                [(*request.key,'WORK_COMPLETED',digest([request.prepared,
                    request.qualification,request.checkpoint,'original_result_consumption_return']),None)])
        self._apply(observed)

    def snapshot(self):
        try:self.owner.require_owner()
        except Exception:self.unavailable()
        if not self.lock.acquire(False):return dict(state='UNKNOWN',reason='CONTENTION',funding_authority=False)
        try:
            latest=self.latest
            return dict(state='UNKNOWN' if self.loss else 'MEASURING',
                contract='ACTUAL_CURRENT_SUBMISSION_AND_NATIVE_COMMIT_RETURNS_NOT_SOURCE_ACK',
                pending_inventory=None if latest is None else dict(count=len(latest[0]),
                    sha256=latest[1],frontier_sha256=latest[2],sequence=latest[3]),
                restored_prefix_closure='UNESTABLISHED',source_closure='UNESTABLISHED',
                inventory_contract='NATIVE_PENDING_GENERATIONS_NOT_CANONICAL_ECONOMIC_ARRIVALS',
                held_protection_closure='UNESTABLISHED',readiness_authority=False,funding_authority=False,
                full_market_rate='UNKNOWN',
                stages={key:project_native_work(value.snapshot()) for key,value in self.stages.items()})
        finally:self.lock.release()


class _Request:
    def __init__(self,owner,identity,key,frontier):
        self.owner=owner;self.identity=identity;self.key=key;self.frontier=frontier
        self.cid=digest(['pons_current_issued_request',identity,key,frontier])
        self.prepared=None;self.vector=None;self.vector_core=None
        self.decision=None;self.qualification=None;self.checkpoint=None


def work_for(plane):
    value=getattr(getattr(plane,'economic_cohorts',None),'current_work',None)
    return value if type(value) is PonsCurrentWork else None


def decided(plane,request,state):
    work=work_for(plane)
    if work is None or request is None:return
    if type(request) is not _Request or request.owner is not work:work.unavailable();return
    work.decision(request,state)


def qualified(plane,request,body):
    work=work_for(plane)
    if work is None or request is None:return
    if type(request) is not _Request or request.owner is not work:work.unavailable();return
    work.qualification(request,body)


def overlaid(plane,request,vector,overlay):
    work=work_for(plane)
    if work is None or request is None:return
    if type(request) is not _Request or request.owner is not work:work.unavailable();return
    work.wallet_overlay(request,vector,overlay)
