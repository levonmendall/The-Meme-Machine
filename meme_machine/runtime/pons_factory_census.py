"""Optional witness of the *existing* native factory replay, without new reads.

This is a frozen, provider-authenticated configured factory domain, not a moving
market universe, held-position census, delivery ACK or permission to operate.
Only the original Preparation.resume and reconciliation traversals feed it.
"""
from functools import wraps
import os
import threading

from .journal import digest

MAX_EVENTS=32768
MAX_RANGES=32768


class PonsFactoryCensus:
    def __init__(self,owner):
        self.owner=owner;self.lock=threading.Lock();self.active=None;self.loss=None
        self.value=self._unknown('NOT_REPLAYED')

    @staticmethod
    def _unknown(reason):
        return dict(state='UNKNOWN',reason=reason,source_complete=False,
            acquisition_complete=False,graduation_resolution='NOT_EVALUATED',
            contract='FROZEN_NATIVE_FACTORY_DOMAIN',current_head_coverage='UNESTABLISHED',
            held_membership='UNESTABLISHED',consumer_completion='UNESTABLISHED',
            qualification_authority=False)

    def start(self,prep):
        if not self.lock.acquire(False):self.loss='CONTENTION';return None
        try:
            self.value=self._unknown('REPLAY_INCOMPLETE')
            if self.active is not None:
                self.active.failed='OVERLAP';return None
            from meme_machine.lanes.pons.pons_historical import Preparation
            from .pons_economic_cohort import PonsEconomicCohorts
            if type(prep) is not Preparation or type(self.owner) is not PonsEconomicCohorts:
                self.loss='OWNER_CHANGED';return None
            self.loss=None
            replay=_Replay(self,prep);self.active=replay;return replay
        finally:self.lock.release()

    def finish(self,replay,success):
        if not self.lock.acquire(False):self.loss='CONTENTION';return
        try:
            if self.active is not replay:
                self.value=self._unknown('OWNER_CHANGED');return
            self.active=None
            self.value=replay.result() if success else self._unknown('NATIVE_REPLAY_FAILED')
            if self.value['source_complete']:
                self.owner.membership.install_factory(replay,self.value)
        except Exception:self.value=self._unknown('MEASUREMENT_FAILED')
        finally:self.lock.release()

    def snapshot(self):
        if not self.lock.acquire(False):return self._unknown('CONTENTION')
        try:return self._unknown(self.loss) if self.loss else dict(self.value)
        finally:self.lock.release()

    def invalidate(self):
        if not self.lock.acquire(False):self.loss='CONTENTION';return
        try:
            self.value=self._unknown('NATIVE_DOMAIN_ADVANCED')
            if self.active is not None:self.active.failed='NATIVE_DOMAIN_ADVANCED'
        finally:self.lock.release()


class _Replay:
    def __init__(self,owner,prep):
        self.owner=owner;self.prep=prep;self.pid=os.getpid();self.failed=None
        self.plan=None;self.expected=None;self.ranges=0;self.events={};self.graduations=set()
        self.reconciled={};self.observation=None;self.prior=None;self.range_digest=None
        self.reconciliation_started=False;self.reconciliation_completed=False

    def population(self,p,count):
        from meme_machine.lanes.pons.pons_historical import SCHEMA,POLICY_HASH,CHAIN_ID,number
        if self.plan is not None or type(count) is not int or not 0<count<=MAX_RANGES:
            raise ValueError('population_bound')
        provider=self.owner.owner.source.split(':')[2]
        if (p['schema']!=SCHEMA or p['policy']!=POLICY_HASH or p['chain_id']!=CHAIN_ID
                or p['provider_fingerprint']!=self.prep.fingerprint or provider!=self.prep.fingerprint):
            raise ValueError('source_identity')
        self.plan=dict(p);self.expected=count
        self.prior=(p['first']-1,None if p['anchor'] is None else p['anchor']['hash'])
        number(p['target'])

    def range(self,first,last,e,logs):
        from meme_machine.lanes.pons.pons_historical import event_id,GRADUATION,number
        p=self.plan
        if (p is None or self.ranges>=self.expected or first!=self.prior[0]+1
                or e['query']!=self.prep.population_filter() or e['chain_id']!=p['chain_id']
                or e['provider_fingerprint']!=p['provider_fingerprint'] or e['policy']!=p['policy']
                or number(e['end'])!=last
                or self.prior[1] is not None and e['previous']['hash']!=self.prior[1]):
            raise ValueError('range_identity')
        if len(self.events)+len(logs)>MAX_EVENTS:raise ValueError('event_bound')
        for event in logs:
            identity=event_id(event)
            if identity in self.events:raise ValueError('duplicate_source_event')
            self.events[identity]=digest([event['blockNumber'],event['transactionIndex'],event['topics'][0]])
            if event['topics'][0]==GRADUATION:self.graduations.add(identity)
        self.ranges+=1;self.prior=(last,e['end']['hash'])
        self.range_digest=digest([self.range_digest,first,last,e['event_digest'],e['identities'],
            e['end'],e['previous'],e['query']])

    def graduation(self,event,token,disposition,present):
        from meme_machine.lanes.pons.pons_historical import event_id,POLICY
        from meme_machine.lanes.pons.pons_natural_observation import ZERO
        identity=event_id(event)
        if identity not in self.graduations or identity in self.reconciled:
            raise ValueError('graduation_census')
        if (disposition is None or disposition['event_identity']!=identity
                or disposition['disposition'] not in (None,'non_native_quote','strategy_horizon_expired')
                or disposition['evidence']['block']!=int(event['blockNumber'],16)
                or disposition['evidence']['block_hash']!=event['blockHash']
                or disposition['evidence']['record']['token'].lower()!=token.lower()
                or disposition['disposition'] is None and present is not True):
            raise ValueError('graduation_disposition')
        terminal=disposition['disposition'];evidence=disposition['evidence']
        native_quote=evidence['record']['pairToken'].lower()==ZERO
        if terminal=='non_native_quote' and native_quote:raise ValueError('native_quote_misclassified')
        if terminal=='strategy_horizon_expired' and (not native_quote or
                int(self.plan['target']['timestamp'],16)-evidence['at']<=POLICY['universe']['max_seconds_after_graduation']):
            # The alternative original expired() predicate depends on a native
            # lifecycle floor not read by this traversal. Do not invent it.
            raise ValueError('native_horizon_unproved')
        self.reconciled[identity]=digest([token,disposition,present])

    def reconciliation(self,completed):
        if completed:
            if not self.reconciliation_started:raise ValueError('reconciliation_not_started')
            self.reconciliation_completed=True
        elif self.reconciliation_started:raise ValueError('reconciliation_repeated')
        else:self.reconciliation_started=True

    def readiness(self,p,result,candidates):
        # Keep only bounded metadata. This is the original rows() result, not a
        # second history scan. Explicit native incomplete/missing counts govern.
        if len(candidates)>MAX_EVENTS:raise ValueError('candidate_bound')
        self.observation=(dict(p),result,digest([[r['id'],r.get('block'),
            r.get('block_hash'),r.get('complete'),r.get('recovery')] for r in candidates]))

    def result(self):
        from meme_machine.lanes.pons.pons_historical import number,POLICY
        unknown=self.owner._unknown
        if self.failed:return unknown(self.failed)
        if (self.pid!=os.getpid() or self.pid!=self.owner.owner.pid
                or getattr(self.prep.history,'economic_cohorts',None) is not self.owner.owner
                or self.prep.history.db.in_transaction or self.plan is None or self.observation is None):
            return unknown('REPLAY_INCOMPLETE')
        p,result,candidate_digest=self.observation;target=p['target'];top=number(target)
        if digest(p)!=digest(self.plan):return unknown('PLAN_CHANGED')
        cutoff=max(0,int(target['timestamp'],16)-POLICY['universe']['max_seconds_after_graduation'])
        if p['cutoff']!=cutoff:return unknown('DOMAIN_IDENTITY')
        if p['prospective'] and cutoff<=p['enrollment_at']:return unknown('PRE_ENROLLMENT_UNOBSERVED')
        if p['first']!=0 and (p['anchor'] is None or number(p['anchor'])!=p['first']-1
                or int(p['anchor']['timestamp'],16)>=cutoff):
            return unknown('DOMAIN_BOUNDARY_UNPROVED')
        if (self.ranges!=self.expected or self.prior!=(top,target['hash']) or self.prep.restored is not True
                or result['seven_day_domain_mature'] is not True
                or result['population_through']!=top or result['target_block']!=top
                or result['missing_ranges']!=0):
            return unknown('CENSUS_INCOMPLETE')
        resolved=(self.reconciliation_completed and self.graduations==self.reconciled.keys()
            and result['pending_graduations']==0 and not result['incomplete_candidates']
            and not result['missing_graduations'])
        return dict(unknown('FROZEN_DOMAIN_VERIFIED' if resolved else 'RESOLUTION_INCOMPLETE'),
            state='OBSERVED',source_complete=resolved,acquisition_complete=True,
            graduation_resolution='COMPLETE' if resolved else 'NOT_EVALUATED',
            provider_fingerprint=p['provider_fingerprint'],policy=p['policy'],chain_id=p['chain_id'],
            genesis_hash=p['genesis_hash'],deployment_digest=digest(p['deployments']),
            first=p['first'],through=top,through_hash=target['hash'],cutoff=cutoff,
            ranges=self.ranges,factory_events=len(self.events),graduations=len(self.graduations),
            event_digest=digest(sorted(self.events.items())),range_digest=self.range_digest,
            disposition_digest=digest(sorted(self.reconciled.items())),candidate_digest=candidate_digest)


def observe_resume(function):
    @wraps(function)
    def observed(prep,*args,**kwargs):
        owner=getattr(prep.history,'economic_cohorts',None)
        census=getattr(owner,'factory',None)
        if census is None:return function(prep,*args,**kwargs)
        replay=None
        try:replay=census.start(prep)
        except Exception:pass
        previous=getattr(prep,'_factory_replay',None);prep._factory_replay=replay
        success=False
        try:
            result=function(prep,*args,**kwargs);success=True;return result
        finally:
            prep._factory_replay=previous
            if replay is not None:
                try:census.finish(replay,success)
                except Exception:pass
    return observed


def record(prep,method,*args):
    replay=getattr(prep,'_factory_replay',None)
    if replay is not None and replay.failed is None:
        try:getattr(replay,method)(*args)
        except Exception:replay.failed='MEASUREMENT_INCOMPLETE'


def invalidate_before(function):
    @wraps(function)
    def observed(prep,*args,**kwargs):
        census=getattr(getattr(prep.history,'economic_cohorts',None),'factory',None)
        if census is not None:
            try:census.invalidate()
            except Exception:pass
        return function(prep,*args,**kwargs)
    return observed
