"""Finite native work populations, distinct from economic arrivals or ACKs.

Adapters must seal an independent complete original traversal and publish actual
native outcomes. This module has no SQL/provider/queue/strategy authority. A
closed stage never means the source, all consumers or protection are complete.
"""
from collections import Counter,deque
import json
import math
import threading
import time

from .economic_cohort import checksum,_hash,MAX_POSITION

MAX_ACTIVE=8
MAX_UNITS=32768
MAX_ROWS=5000
MAX_BYTES=8*1024*1024
MAX_COHORTS=8192
MAX_SUMMARIES=16
STAGES=('DISCOVERY_INPUT','NATIVE_PREPARATION','NATIVE_EVALUATION','NATIVE_WORK_DISPOSITION','HELD_PROTECTION')
TERMINAL={
    'DISCOVERY_INPUT':('NATIVE_FILTERED','POLICY_FILTERED','COALESCED_NOT_DUE','REQUESTED','HISTORY_COMMITTED'),
    'NATIVE_PREPARATION':('HISTORY_COMMITTED',),
    'NATIVE_EVALUATION':('DECISION_COMMITTED',),
    'NATIVE_WORK_DISPOSITION':('WORK_COMPLETED','POLICY_RETIRED'),
    'HELD_PROTECTION':('PROTECTION_OBSERVED',),
}
PENDING=('DEFERRED','INCOMPLETE','MISSING_HISTORY','MISSING_CREATION','COVERAGE_UNAVAILABLE')
COMMITTED=('HISTORY_COMMITTED','DECISION_COMMITTED','WORK_COMPLETED','POLICY_RETIRED')


def project_native_work(value):
    """Fixed bounded public stage metadata; samples never replace its census."""
    try:
        if (type(value) is not dict or value.get('schema')!='native-work-cohort-v1'
                or value.get('stage') not in STAGES or value.get('state') not in ('MEASURING','UNKNOWN')):
            raise ValueError('shape')
        result=dict(schema='native-work-cohort-v1',stage=value['stage'],state=value['state'],
            binding_sha256=_hash(value['binding_sha256']),
            cumulative_summary_sha256=_hash(value['cumulative_summary_sha256']),
            historical_completion=False,readiness_authority=False,funding_authority=False)
        reason=value.get('reason')
        if reason not in (None,'NATIVE_BOUNDARY_UNAVAILABLE','TRANSACTION_FAILED','BOUND','CONTENTION'):
            raise ValueError('reason')
        result['reason']=reason
        def integer(number):
            if type(number) is not int or not 0<=number<=MAX_POSITION:raise ValueError('integer')
            return number
        def clock(number):
            if type(number) not in (int,float) or not math.isfinite(number) or number<0:raise ValueError('clock')
            return number
        for key in ('active_cohorts','expected_units','metadata_bytes','pending_units',
                    'completed_cohorts','summary_evictions'):
            result[key]=integer(value[key])
        result['bounds']=dict(active=MAX_ACTIVE,units=MAX_UNITS,rows=MAX_ROWS,
            metadata_bytes=MAX_BYTES,cohorts=MAX_COHORTS,summaries=MAX_SUMMARIES)
        allowed=(*TERMINAL[value['stage']],*PENDING)
        def row(item,closed):
            if type(item) is not dict:raise ValueError('row')
            answer={key:_hash(item[key]) for key in ('cohort_sha256','frontier_sha256','expected_sha256')}
            answer['expected_units']=integer(item['expected_units'])
            dispositions=item['dispositions']
            if type(dispositions) is not dict or len(dispositions)>len(allowed):raise ValueError('dispositions')
            answer['dispositions']={name:integer(count) for name,count in dispositions.items() if name in allowed}
            if len(answer['dispositions'])!=len(dispositions):raise ValueError('dispositions')
            if closed:
                if any(name not in TERMINAL[value['stage']] for name in answer['dispositions']):
                    raise ValueError('closed_pending')
                for key in ('traversal_sha256','outcomes_sha256'):answer[key]=_hash(item[key])
                for key in ('first_observed_monotonic','completion_observed_monotonic'):answer[key]=clock(item[key])
                answer['committed_units']=integer(item['committed_units'])
                if (sum(answer['dispositions'].values())!=answer['expected_units']
                        or answer['committed_units']!=sum(count for name,count in answer['dispositions'].items() if name in COMMITTED)
                        or answer['completion_observed_monotonic']<answer['first_observed_monotonic']):
                    raise ValueError('population')
            else:
                if type(item['census_sealed']) is not bool:raise ValueError('seal')
                answer['census_sealed']=item['census_sealed'];answer['observed_units']=integer(item['observed_units'])
                if (sum(answer['dispositions'].values())!=answer['observed_units']
                        or answer['observed_units']>answer['expected_units']):raise ValueError('population')
            return answer
        for key,maximum in (('active',MAX_ACTIVE),('closed',MAX_SUMMARIES)):
            rows=value[key]
            if type(rows) is not list or len(rows)>maximum:raise ValueError('bound')
            # Validate every advertised row, then retain only fixed samples.
            selected=[row(item,key=='closed') for item in rows]
            omitted=integer(value.get(key+'_samples_omitted',0))
            if omitted+len(selected)>maximum:raise ValueError('bound')
            result[key]=selected[-4:]
            result[key+'_samples_omitted']=omitted+len(selected)-len(result[key])
        if len(value['active'])+value.get('active_samples_omitted',0)!=result['active_cohorts']:
            raise ValueError('population')
        if (result['completed_cohorts']-result['summary_evictions']
                !=len(value['closed'])+value.get('closed_samples_omitted',0)
                or result['pending_units']>result['expected_units']
                or result['expected_units']>MAX_UNITS or result['metadata_bytes']>MAX_BYTES):
            raise ValueError('population')
        result['contract']='NATIVE_STAGE_COUNTS_AND_DIGESTS_WITH_EXPLICIT_SAMPLES_NOT_ALL_CONSUMER_COMPLETION'
        result['full_market_rate']='UNKNOWN_REQUIRES_BOUND_SOURCE_AND_ALL_NATIVE_STAGES'
        if len(json.dumps(result,allow_nan=False).encode())>8192:raise ValueError('bound')
        return result
    except Exception:return dict(state='UNKNOWN',reason='PROJECTION_UNAVAILABLE',funding_authority=False)


class NativeWorkCohorts:
    def __init__(self,binding,stage,*,clock=time.monotonic):
        if type(binding) is not dict or not binding or len(binding)>16 or stage not in STAGES:
            raise ValueError('native_work_binding')
        detached={}
        for key,value in binding.items():
            if type(key) is not str or not 0<len(key)<=64:raise ValueError('native_work_binding')
            if type(value) is str:
                if not 0<len(value)<=256:raise ValueError('native_work_binding')
            elif type(value) is not int or not 0<=value<=MAX_POSITION:raise ValueError('native_work_binding')
            detached[key]=value
        self.binding=checksum(detached);self.stage=stage;self.clock=clock
        self.lock=threading.Lock();self.loss=None;self.active={};self.seen={}
        self.units=0;self.bytes=0;self.completed=0;self.evictions=0;self.chain='0'*64
        self.closed=deque(maxlen=MAX_SUMMARIES)
        self.last_clock=None

    def unavailable(self,reason='NATIVE_BOUNDARY_UNAVAILABLE'):
        if reason not in ('NATIVE_BOUNDARY_UNAVAILABLE','TRANSACTION_FAILED','BOUND'):
            reason='NATIVE_BOUNDARY_UNAVAILABLE'
        if self.loss is None:self.loss=reason

    def _apply(self,operation):
        if self.loss:return
        if not self.lock.acquire(False):self.loss='CONTENTION';return
        try:operation()
        except Exception:self.unavailable()
        finally:self.lock.release()

    def _now(self):
        value=self.clock()
        if (type(value) not in (int,float) or not math.isfinite(value) or value<0
                or self.last_clock is not None and value<self.last_clock):raise ValueError('clock')
        self.last_clock=value
        return value

    def begin(self,cohort_sha256,frontier_sha256):
        def apply():
            cid=_hash(cohort_sha256);frontier=_hash(frontier_sha256)
            if cid in self.seen:raise ValueError('reopen')
            if cid in self.active:
                if self.active[cid]['frontier']!=frontier:raise ValueError('conflict')
                return
            if len(self.active)>=MAX_ACTIVE or len(self.seen)+len(self.active)>=MAX_COHORTS:
                self.unavailable('BOUND');return
            self.active[cid]=dict(frontier=frontier,expected={},outcomes={},seal=None,first=self._now())
        self._apply(apply)

    def expect(self,cohort_sha256,rows):
        def apply():
            row=self.active[_hash(cohort_sha256)]
            if type(rows) not in (tuple,list) or len(rows)>MAX_ROWS:raise ValueError('bound')
            for item in rows:
                if type(item) not in (tuple,list) or len(item)!=2:raise ValueError('row')
                key,value=map(_hash,item);old=row['expected'].get(key)
                if old is not None:
                    if old!=value:raise ValueError('conflict')
                    continue
                if row['seal'] is not None:raise ValueError('sealed')
                if self.units>=MAX_UNITS or self.bytes+160>MAX_BYTES:
                    self.unavailable('BOUND');return
                row['expected'][key]=value;self.units+=1;self.bytes+=160
        self._apply(apply)

    def seal_expected(self,cohort_sha256,count,digest,traversal_sha256):
        def apply():
            cid=_hash(cohort_sha256);row=self.active[cid]
            if type(count) is not int or not 0<=count<=MAX_UNITS:raise ValueError('count')
            seal=(count,_hash(digest),_hash(traversal_sha256))
            actual=tuple(sorted(row['expected'].items()))
            if count!=len(actual) or seal[1]!=checksum(actual):raise ValueError('census')
            if row['seal'] is not None and row['seal']!=seal:raise ValueError('conflict')
            row['seal']=seal;self._finish(cid)
        self._apply(apply)

    def observe(self,cohort_sha256,rows):
        def apply():
            cid=_hash(cohort_sha256);row=self.active[cid]
            if type(rows) not in (tuple,list) or len(rows)>MAX_ROWS:raise ValueError('bound')
            for item in rows:
                if type(item) not in (tuple,list) or len(item)!=5:raise ValueError('row')
                key,input_hash,disposition,receipt,next_due=item
                key=_hash(key);input_hash=_hash(input_hash)
                if row['expected'].get(key)!=input_hash:raise ValueError('unknown')
                if disposition not in (*TERMINAL[self.stage],*PENDING):raise ValueError('disposition')
                if receipt is not None:receipt=_hash(receipt)
                if disposition in COMMITTED and receipt is None:raise ValueError('native_receipt')
                if next_due is not None and (type(next_due) not in (int,float)
                        or not math.isfinite(next_due) or next_due<0):raise ValueError('due')
                if disposition in ('DEFERRED','COALESCED_NOT_DUE') and next_due is None:raise ValueError('due')
                outcome=(disposition,receipt,next_due)
                old=row['outcomes'].get(key)
                if old is not None:
                    if old[:3]==outcome:continue
                    if old[0] in TERMINAL[self.stage]:raise ValueError('changed_terminal')
                    # A retry may actually finish an unresolved original work
                    # unit. It does not change that unit's expected input.
                elif self.bytes+96>MAX_BYTES:self.unavailable('BOUND');return
                else:self.bytes+=96
                row['outcomes'][key]=(*outcome,self._now())
            self._finish(cid)
        self._apply(apply)

    def _finish(self,cid):
        row=self.active[cid]
        if row['seal'] is None:return
        # Expected membership is sealed before outcomes; the public expect()
        # path rejects every later expansion/change. An incomplete population
        # cannot close, so do not sort/hash all its members for each outcome.
        # The complete native census is still checked immediately before any
        # closure, including a same-cardinality corruption of stored members.
        count=row['seal'][0]
        if len(row['expected'])!=count:raise ValueError('changed_census')
        if (len(row['outcomes'])!=count or any(value[0] not in TERMINAL[self.stage]
                for value in row['outcomes'].values())):return
        actual=tuple(sorted(row['expected'].items()))
        if (len(actual),checksum(actual))!=row['seal'][:2]:raise ValueError('changed_census')
        now=self._now();clocks=[value[3] for value in row['outcomes'].values()]
        if now<row['first'] or any(value>now for value in clocks):raise ValueError('clock')
        counts=dict(sorted(Counter(value[0] for value in row['outcomes'].values()).items()))
        result=dict(cohort_sha256=cid,frontier_sha256=row['frontier'],expected_units=len(actual),
            expected_sha256=row['seal'][1],traversal_sha256=row['seal'][2],dispositions=counts,
            outcomes_sha256=checksum(sorted((key,*value[:3]) for key,value in row['outcomes'].items())),
            first_observed_monotonic=row['first'],completion_observed_monotonic=now,
            committed_units=sum(counts.get(key,0) for key in COMMITTED))
        self.completed+=1;self.chain=checksum([self.chain,result]);self.seen[cid]=row['seal']
        if len(self.closed)==MAX_SUMMARIES:self.evictions+=1
        self.closed.append(result)
        self.units-=len(actual);self.bytes-=160*len(actual)+96*len(row['outcomes']);del self.active[cid]

    def snapshot(self):
        if not self.lock.acquire(False):
            return dict(state='UNKNOWN',reason='CONTENTION',funding_authority=False)
        try:
            return dict(schema='native-work-cohort-v1',binding_sha256=self.binding,stage=self.stage,
                state='UNKNOWN' if self.loss else 'MEASURING',reason=self.loss,
                contract='EXACT_NATIVE_TRAVERSAL_AND_STAGE_OUTCOMES_NOT_SOURCE_OR_ALL_CONSUMER_COMPLETION',
                active_cohorts=len(self.active),expected_units=self.units,metadata_bytes=self.bytes,
                pending_units=sum(len(row['expected'])-sum(value[0] in TERMINAL[self.stage]
                    for value in row['outcomes'].values()) for row in self.active.values()),
                active=[dict(cohort_sha256=cid,frontier_sha256=row['frontier'],
                    expected_units=len(row['expected']),expected_sha256=checksum(tuple(sorted(row['expected'].items()))),
                    census_sealed=row['seal'] is not None,observed_units=len(row['outcomes']),
                    dispositions=dict(sorted(Counter(value[0] for value in row['outcomes'].values()).items())))
                    for cid,row in sorted(self.active.items())],
                completed_cohorts=self.completed,summary_evictions=self.evictions,cumulative_summary_sha256=self.chain,
                closed=[dict(row,dispositions=dict(row['dispositions'])) for row in self.closed],
                bounds=dict(active=MAX_ACTIVE,units=MAX_UNITS,rows=MAX_ROWS,metadata_bytes=MAX_BYTES,
                    cohorts=MAX_COHORTS,summaries=MAX_SUMMARIES),
                full_market_rate='UNKNOWN_REQUIRES_BOUND_SOURCE_AND_ALL_NATIVE_STAGES',
                historical_completion=False,readiness_authority=False,funding_authority=False)
        finally:self.lock.release()
