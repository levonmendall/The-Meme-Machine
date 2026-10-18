"""Bounded diagnostic reconciliation of real source/COMMIT/FULL-ACK cohorts.

No writer, provider, readiness or funding authority. Native adapters supply
already validated identities, source closure and post-COMMIT observations. A
missing hook, contention, conflict or bound is UNKNOWN, never a smaller census.
"""
from collections import deque
import hashlib
import json
import math
import threading
import time

MAX_ACTIVE=8
MAX_IDENTITIES=8192
MAX_OBLIGATIONS=16384
MAX_BYTES=4*1024*1024
MAX_SUMMARIES=16
MAX_COHORTS=8192
MAX_POSITION=2**63-1


def checksum(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _text(value,maximum=256):
    if type(value) is not str or not 0<len(value)<=maximum:raise ValueError('shape')
    return value


def _hash(value):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('shape')
    return value


def _rows(values,committed=False):
    result=[]
    if type(values) not in (tuple,list) or len(values)>2048:raise ValueError('bound')
    for row in values:
        if type(row) not in (tuple,list) or len(row)!=(6 if committed else 5):raise ValueError('shape')
        scope,identity,digest,position,available=row[:5]
        if type(position) is not int or not 0<=position<=MAX_POSITION:raise ValueError('shape')
        if type(available) not in (int,float) or not math.isfinite(available) or available<0:raise ValueError('shape')
        value=(_text(scope),_text(identity),_hash(digest),position,available)
        if committed:
            if type(row[5]) is not bool:raise ValueError('shape')
            value+=row[5],
        result.append(value)
    return result


class EconomicCohorts:
    """One process/run binding; metadata is discarded only after reconciliation."""
    def __init__(self,lane,binding,*,clock=time.monotonic):
        if lane not in ('pump','pons'):raise ValueError('economic_cohort_lane')
        if type(binding) is not dict or not binding or len(binding)>12:raise ValueError('economic_cohort_binding')
        # Detach only small fixed producer identity fields, never credentials.
        self.binding={_text(k,64):_text(v,256) if type(v) is str else v for k,v in binding.items()}
        if any(type(v) not in (str,int) or type(v) is bool for v in self.binding.values()):
            raise ValueError('economic_cohort_binding')
        if any(type(v) is int and not 0<=v<2**128 for v in self.binding.values()):
            raise ValueError('economic_cohort_binding')
        self.binding_hash=checksum(self.binding);self.lane=lane;self.clock=clock
        self.lock=threading.Lock();self.loss=None;self.active={};self.obligations={}
        self.identities=0;self.bytes=0;self.closed=deque(maxlen=MAX_SUMMARIES)
        self.completed=0;self.summary_evictions=0;self.cumulative_chain='0'*64
        self.cohort_ids=set()

    def _run(self,operation):
        if self.loss:return
        if not self.lock.acquire(False):self.loss='CONTENTION';return
        try:operation()
        except Exception:self.loss='INVALID_OR_UNAVAILABLE_MEASUREMENT'
        finally:self.lock.release()

    def unavailable(self,reason='NATIVE_BOUNDARY_UNAVAILABLE'):
        # Fixed label, not caller exception/provider text.
        self.loss=reason if reason in ('NATIVE_BOUNDARY_UNAVAILABLE','BOUND','GAP','TRANSACTION_FAILED',
            'SOURCE_CLOSURE_UNAVAILABLE','UNSUPPORTED_PATH') else 'NATIVE_BOUNDARY_UNAVAILABLE'

    def open(self,cohort_id,scope_ids):
        def apply():
            if type(scope_ids) not in (list,tuple) or not 0<len(scope_ids)<=256:raise ValueError('bound')
            identity=_text(cohort_id);scopes=tuple(sorted(_text(s) for s in scope_ids))
            if not 0<len(scopes)<=256 or len(set(scopes))!=len(scopes):raise ValueError('shape')
            if identity in self.active:
                if self.active[identity]['scopes']!=scopes:raise ValueError('scope_conflict')
                return
            stamp=checksum(identity)
            if stamp in self.cohort_ids:raise ValueError('reopened_cohort')
            scope_bytes=sum(len(s.encode()) for s in scopes)
            if len(self.cohort_ids)>=MAX_COHORTS or self.bytes+96+scope_bytes>MAX_BYTES:
                self.unavailable('BOUND');return
            if len(self.active)>=MAX_ACTIVE:self.unavailable('BOUND');return
            self.cohort_ids.add(stamp);self.bytes+=96+scope_bytes
            self.active[identity]=dict(scopes=scopes,arrivals={},committed={},fanout={},
                first=self.clock(),last=None,closure=None)
        self._run(apply)

    def arrivals(self,cohort_id,rows):
        def apply():
            cohort=self.active[cohort_id]
            for row in _rows(rows):
                key=row[:2];prior=cohort['arrivals'].get(key)
                if row[0] not in cohort['scopes']:raise ValueError('scope')
                if prior is not None:
                    if prior[:4]!=row[:4]:raise ValueError('conflict')
                    continue
                size=sum(len(v.encode()) for v in row[:3])+32
                if self.identities>=MAX_IDENTITIES or self.bytes+size>MAX_BYTES:
                    self.unavailable('BOUND');return
                cohort['arrivals'][key]=row;self.identities+=1;self.bytes+=size
        self._run(apply)

    def committed(self,cohort_id,rows,obligations,*,fanout_complete=None):
        """Call only after the original outer source transaction COMMIT."""
        def apply():
            cohort=self.active[cohort_id]
            published=_rows(rows,True);expected={};seen={}
            if self.lane=='pump':
                if type(fanout_complete) not in (list,tuple) or len(fanout_complete)>2048:raise ValueError('fanout_witness')
                for scope,event,count,digest in fanout_complete:
                    key=(_text(scope),_text(event))
                    if type(count) is not int or not 0<=count<=MAX_OBLIGATIONS or key in expected:raise ValueError('fanout_witness')
                    expected[key]=(count,_hash(digest));seen[key]=(0,hashlib.sha256())
                if set(expected)!={row[:2] for row in published}:raise ValueError('fanout_membership')
            for row in published:
                key=row[:2];arrival=cohort['arrivals'].get(key)
                if arrival is None or arrival[:4]!=row[:4]:raise ValueError('membership')
                old=cohort['committed'].get(key)
                if old is not None and old[:4]!=row[:4]:raise ValueError('conflict')
                # Replay cannot turn a prior new identity into another arrival.
                if old is None:cohort['committed'][key]=row
                cohort['fanout'].setdefault(key,set())
            if type(obligations) not in (list,tuple) or len(obligations)>MAX_OBLIGATIONS:raise ValueError('bound')
            for row in obligations:
                if type(row) not in (tuple,list) or len(row)!=5:raise ValueError('shape')
                identity,scope,event,source_hash,consumer=row
                value=(_text(identity),_text(scope),_text(event),_hash(source_hash),_text(consumer))
                key=value[1:3]
                if key not in cohort['committed']:raise ValueError('membership')
                if self.lane=='pump':
                    if key not in seen:raise ValueError('fanout_membership')
                    count,hasher=seen[key];hasher.update(len(value[0].encode()).to_bytes(4,'big')+value[0].encode());seen[key]=(count+1,hasher)
                prior=self.obligations.get(value[0])
                if prior is not None:
                    if prior['value']!=value:raise ValueError('conflict')
                    prior['cohorts'].add(cohort_id)
                else:
                    size=sum(len(v.encode()) for v in value)+32
                    if len(self.obligations)>=MAX_OBLIGATIONS or self.bytes+size>MAX_BYTES:
                        self.unavailable('BOUND');return
                    self.obligations[value[0]]=dict(value=value,acked=False,cohorts={cohort_id},bytes=size)
                    self.bytes+=size
                cohort['fanout'][key].add(value[0])
            if any(expected[key]!=(count,hasher.hexdigest()) for key,(count,hasher) in seen.items()):
                raise ValueError('fanout_incomplete')
            cohort['last']=self.clock();self._finish(cohort_id)
        self._run(apply)

    def acknowledged(self,obligations):
        """After original FULL consumer verification and canonical ACK COMMIT."""
        def apply():
            if self.lane!='pump':raise ValueError('delivery_contract')
            if type(obligations) not in (list,tuple) or len(obligations)>64:raise ValueError('bound')
            changed=set()
            for identity,source_hash in obligations:
                row=self.obligations.get(identity)
                if row is None:continue # Unmeasured preexisting/candidate cohort.
                if row['value'][3]!=_hash(source_hash):raise ValueError('ack_conflict')
                row['acked']=True;changed.update(row['cohorts'])
            for identity in sorted(changed):self._finish(identity)
        self._run(apply)

    def seal(self,cohort_id,lower,upper,source_digest,*,complete,expected_economics=None):
        """An owned adapter's actual complete-source witness, not an authority."""
        def apply():
            if (type(lower) is not int or type(upper) is not int or not 0<=lower<=upper<=MAX_POSITION
                    or type(complete) is not bool):
                raise ValueError('shape')
            cohort=self.active[cohort_id]
            if any(not lower<=row[3]<=upper for row in cohort['arrivals'].values()):raise ValueError('interval')
            if self.lane=='pump' and complete:
                if type(expected_economics) not in (tuple,list) or len(expected_economics)!=2:
                    raise ValueError('decoder_census')
                count,digest=expected_economics
                if type(count) is not int or not 0<=count<=MAX_IDENTITIES:raise ValueError('decoder_census')
                if (count,_hash(digest))!=(len(cohort['arrivals']),
                        checksum(sorted(row[:4] for row in cohort['arrivals'].values()))):
                    raise ValueError('decoder_census_mismatch')
            closure=(lower,upper,_hash(source_digest),complete)
            if cohort['closure'] is not None and cohort['closure']!=closure:raise ValueError('closure_conflict')
            cohort['closure']=closure;self._finish(cohort_id)
        self._run(apply)

    def _finish(self,identity):
        cohort=self.active[identity];closure=cohort['closure']
        # Pons native history publication has no established equivalent of the
        # Solana authenticated consumer FULL-COMMIT plus canonical source ACK.
        # A source interval alone must never imply its consumer completion.
        if self.lane!='pump':return
        if (closure is None or not closure[3] or cohort['last'] is None
                or set(cohort['arrivals'])!=set(cohort['committed'])):return
        fanout=set().union(*cohort['fanout'].values()) if cohort['fanout'] else set()
        if any(not self.obligations[key]['acked'] for key in fanout):return
        arrival_digest=checksum(sorted(row[:4] for row in cohort['arrivals'].values()))
        obligation_digest=checksum(sorted(self.obligations[key]['value'] for key in fanout))
        row=dict(state='CLOSED_COHORT_RECONCILED',cohort_sha256=checksum(identity),
            lower=closure[0],upper=closure[1],source_sha256=closure[2],
            unique_economics=len(cohort['arrivals']),new_canonical=sum(r[5] for r in cohort['committed'].values()),
            replay_canonical=sum(not r[5] for r in cohort['committed'].values()),
            fanout_obligations=len(fanout),verified_full_acks=len(fanout),
            fanout_scope='COMPLETE_BINDINGS_AT_EACH_CANONICAL_COMMIT_NOT_FUTURE_MEMBERSHIP',
            economic_sha256=arrival_digest,fanout_sha256=obligation_digest,
            original_available_wall_min=min((r[4] for r in cohort['arrivals'].values()),default=None),
            original_available_wall_max=max((r[4] for r in cohort['arrivals'].values()),default=None),
            first_observed_monotonic=cohort['first'],last_commit_observed_monotonic=cohort['last'],
            completion_observed_monotonic=self.clock())
        self.cumulative_chain=checksum([self.cumulative_chain,row]);self.completed+=1
        if len(self.closed)==MAX_SUMMARIES:self.summary_evictions+=1
        self.closed.append(row)
        for key in fanout:
            obligation=self.obligations[key];obligation['cohorts'].discard(identity)
            if not obligation['cohorts']:self.bytes-=obligation['bytes'];del self.obligations[key]
        for value in cohort['arrivals'].values():self.bytes-=sum(len(v.encode()) for v in value[:3])+32
        self.bytes-=sum(len(s.encode()) for s in cohort['scopes'])
        self.identities-=len(cohort['arrivals']);del self.active[identity]

    def snapshot(self):
        if not self.lock.acquire(False):
            return dict(state='UNKNOWN',reason='CONTENTION',funding_authority=False)
        try:
            return dict(schema='native-economic-cohort-v1',lane=self.lane,binding_sha256=self.binding_hash,
                state='UNKNOWN' if self.loss else 'MEASURING',reason=self.loss,
                delivery_contract=('SOLANA_CONSUMER_FULL_COMMIT_AND_SOURCE_ACK' if self.lane=='pump'
                    else 'PONS_CONSUMER_COMPLETION_UNESTABLISHED'),
                classification_contract='NATIVE_CANONICAL_INSERT_NOT_GLOBAL_FIRST_ARRIVAL',
                active_cohorts=len(self.active),active_identities=self.identities,
                active_fanout=len(self.obligations),pending_full_ack=(sum(not r['acked'] for r in self.obligations.values())
                    if self.lane=='pump' else None),
                active=[dict(cohort_sha256=checksum(identity),scope_sha256=checksum(cohort['scopes']),
                    unique_economics=len(cohort['arrivals']),canonical_publications=len(cohort['committed']),
                    native_new=sum(r[5] for r in cohort['committed'].values()),
                    native_replay=sum(not r[5] for r in cohort['committed'].values()),
                    economic_sha256=checksum(sorted(r[:4] for r in cohort['arrivals'].values())),
                    publication_sha256=checksum(sorted(r[:4] for r in cohort['committed'].values())),
                    lower=None if cohort['closure'] is None else cohort['closure'][0],
                    upper=None if cohort['closure'] is None else cohort['closure'][1],
                    source_complete=cohort['closure'] is not None and cohort['closure'][3],
                    source_sha256=None if cohort['closure'] is None else cohort['closure'][2])
                    for identity,cohort in sorted(self.active.items())],
                completed_cohorts=self.completed,summary_evictions=self.summary_evictions,
                cumulative_summary_sha256=self.cumulative_chain,closed=[dict(row) for row in self.closed],
                bounds=dict(active=MAX_ACTIVE,identities=MAX_IDENTITIES,obligations=MAX_OBLIGATIONS,
                    cohorts=MAX_COHORTS,metadata_bytes=MAX_BYTES),
                full_market_rate='UNKNOWN_REQUIRES_CONTIGUOUS_SOURCE_AND_FRESH_HEAD_CENSUS',
                historical_completion=False,readiness_authority=False,funding_authority=False)
        finally:self.lock.release()
