"""Finite native work populations, distinct from economic arrivals or ACKs.

Adapters must seal an independent complete original traversal and publish actual
native outcomes. This module has no SQL/provider/queue/strategy authority. A
closed stage never means the source, all consumers or protection are complete.
"""
from collections import Counter,deque
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
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('clock')
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
        actual=tuple(sorted(row['expected'].items()))
        if (len(actual),checksum(actual))!=row['seal'][:2]:raise ValueError('changed_census')
        if (len(row['outcomes'])!=len(actual) or any(value[0] not in TERMINAL[self.stage]
                for value in row['outcomes'].values())):return
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
