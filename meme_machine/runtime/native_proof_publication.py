"""Bounded observations of the original source proof publication COMMIT.

IDs are registered by committed native defer_proof calls, expected membership
comes from complete linked source coverage, and outcomes come from the original
publisher after its outer COMMIT. This ledger cannot publish a proof or ACK.
"""
from collections import deque
import math
import threading
import time

from .economic_cohort import checksum,_hash,MAX_COHORTS

MAX_ACTIVE=8
MAX_PROOFS=512
MAX_CLOSED=16
MAX_SAMPLES=4
ACTIVE_FIELDS=('cohort_sha256','source_sha256','proof_ids_sha256','lower','upper',
    'required_proofs','published_proofs')
CLOSED_FIELDS=('cohort_sha256','source_sha256','proof_ids_sha256','lower','upper',
    'published_proofs','first_post_commit_monotonic','last_post_commit_monotonic',
    'completion_observed_monotonic')


class NativeProofPublications:
    def __init__(self,binding_sha256):
        self.binding=_hash(binding_sha256);self.lock=threading.Lock();self.loss=None
        self.known={};self.active={};self.seen={};self.closed=deque(maxlen=MAX_CLOSED)
        self.completed=0;self.evictions=0;self.chain='0'*64

    def _apply(self,operation):
        if self.loss:return
        if not self.lock.acquire(False):self.loss='CONTENTION';return
        try:operation()
        except Exception:self.loss='INVALID_OR_UNAVAILABLE_MEASUREMENT'
        finally:self.lock.release()

    def register(self,identity,proof_sha256):
        def apply():
            key=_hash(identity);body=_hash(proof_sha256);old=self.known.get(key)
            if old is not None:
                if old[0]!=body:raise ValueError('conflict')
                return
            if len(self.known)>=MAX_PROOFS:raise ValueError('bound')
            self.known[key]=[body,None]
        self._apply(apply)

    def expect(self,cohort,lower,upper,source_sha256,identities):
        def apply():
            if type(cohort) is not str or not 0<len(cohort)<=128:raise ValueError('cohort')
            if (type(lower) is not int or type(upper) is not int or not 0<=lower<=upper<2**63
                    or type(identities) not in (tuple,list) or not 0<len(identities)<=64):
                raise ValueError('bound')
            keys=tuple(sorted({_hash(key) for key in identities}))
            if len(keys)!=len(identities) or any(key not in self.known for key in keys):
                raise ValueError('missing')
            cid=checksum(cohort);source=_hash(source_sha256);members=checksum(keys)
            signature=checksum([lower,upper,source,keys]);old=self.seen.get(cid)
            if old is not None:
                if old!=signature:raise ValueError('conflict')
                return
            if len(self.active)>=MAX_ACTIVE or len(self.seen)>=MAX_COHORTS:raise ValueError('bound')
            self.seen[cid]=signature
            self.active[cid]=dict(lower=lower,upper=upper,source=source,members=members,keys=keys)
            self._finish()
        self._apply(apply)

    def published(self,rows):
        """Called only after the native publisher's actual outer transaction."""
        def apply():
            if type(rows) not in (tuple,list) or len(rows)>64:raise ValueError('bound')
            now=time.monotonic()
            if not math.isfinite(now) or now<0:raise ValueError('clock')
            for row in rows:
                if type(row) not in (tuple,list) or len(row)!=2:raise ValueError('row')
                key,body=map(_hash,row);old=self.known.get(key)
                # Pre-epoch/replay proofs outside the observed source windows
                # remain native work; they cannot close a measured population.
                if old is None:continue
                if old[0]!=body:raise ValueError('conflict')
                if old[1] is None:old[1]=now
            self._finish()
        self._apply(apply)

    def _finish(self):
        for cid,row in list(self.active.items()):
            times=[self.known[key][1] for key in row['keys']]
            if any(value is None for value in times):continue
            now=time.monotonic()
            if not math.isfinite(now) or now<max(times):raise ValueError('clock')
            result=[cid,row['source'],row['members'],row['lower'],row['upper'],len(times),
                min(times),max(times),now]
            self.completed+=1;self.chain=checksum([self.chain,result])
            if len(self.closed)==MAX_CLOSED:self.evictions+=1
            self.closed.append(result);del self.active[cid]

    def retain(self,identities):
        """Drop metadata only after no open source window or pending join uses it."""
        def apply():
            if type(identities) not in (tuple,list,set) or len(identities)>MAX_PROOFS:
                raise ValueError('bound')
            live={_hash(key) for key in identities}
            for row in self.active.values():live.update(row['keys'])
            for key in tuple(self.known):
                if key not in live:del self.known[key]
        self._apply(apply)

    def snapshot(self):
        if not self.lock.acquire(False):
            return dict(state='UNKNOWN',reason='CONTENTION',funding_authority=False)
        try:
            active=[[cid,row['source'],row['members'],row['lower'],row['upper'],len(row['keys']),
                sum(self.known[key][1] is not None for key in row['keys'])]
                for cid,row in sorted(self.active.items())]
            closed=list(self.closed)
            return dict(schema='native-source-proof-publication-v1',binding_sha256=self.binding,
                state='UNKNOWN' if self.loss else 'MEASURING',reason=self.loss,
                contract='LINKED_SOURCE_PROOF_IDS_AND_ORIGINAL_POST_COMMIT_PUBLICATION_NOT_HISTORY_ACK',
                active_windows=len(active),known_proofs=len(self.known),completed_windows=self.completed,
                summary_evictions=self.evictions,cumulative_summary_sha256=self.chain,
                active_fields=list(ACTIVE_FIELDS),active=active[-MAX_SAMPLES:],
                active_omitted=max(0,len(active)-MAX_SAMPLES),active_sha256=checksum(active),
                closed_fields=list(CLOSED_FIELDS),closed=[list(row) for row in closed[-MAX_SAMPLES:]],
                closed_omitted=max(0,len(closed)-MAX_SAMPLES),closed_sha256=checksum(closed),
                bounds=dict(active=MAX_ACTIVE,proofs=MAX_PROOFS,closed=MAX_CLOSED,samples=MAX_SAMPLES),
                historical_completion=False,readiness_authority=False,funding_authority=False)
        finally:self.lock.release()


def projection(value,binding_sha256):
    """Fixed compact samples plus complete-population counts and digests."""
    import json
    try:
        if type(value) is not dict or len(value)>28:raise ValueError('shape')
        fixed=dict(schema='native-source-proof-publication-v1',binding_sha256=_hash(binding_sha256),
            contract='LINKED_SOURCE_PROOF_IDS_AND_ORIGINAL_POST_COMMIT_PUBLICATION_NOT_HISTORY_ACK',
            historical_completion=False,readiness_authority=False,funding_authority=False,
            active_fields=list(ACTIVE_FIELDS),closed_fields=list(CLOSED_FIELDS),
            bounds=dict(active=MAX_ACTIVE,proofs=MAX_PROOFS,closed=MAX_CLOSED,samples=MAX_SAMPLES))
        if any(type(value.get(k)) is not type(v) or value[k]!=v for k,v in fixed.items()):raise ValueError('contract')
        if value.get('state') not in ('MEASURING','UNKNOWN') or value.get('reason') not in (
                None,'CONTENTION','INVALID_OR_UNAVAILABLE_MEASUREMENT'):raise ValueError('state')
        def count(v,maximum=2**63-1):
            if type(v) is not int or not 0<=v<=maximum:raise ValueError('count')
            return v
        result=dict(fixed,state=value['state'],reason=value['reason'])
        for key in ('active_windows','known_proofs','completed_windows','summary_evictions','active_omitted','closed_omitted'):
            result[key]=count(value[key])
        if result['active_windows']>MAX_ACTIVE or result['known_proofs']>MAX_PROOFS:raise ValueError('bound')
        for key in ('cumulative_summary_sha256','active_sha256','closed_sha256'):result[key]=_hash(value[key])
        for name,fields in (('active',ACTIVE_FIELDS),('closed',CLOSED_FIELDS)):
            rows=value[name]
            if type(rows) is not list or len(rows)>MAX_SAMPLES:raise ValueError('bound')
            result[name]=[]
            for row in rows:
                if type(row) is not list or len(row)!=len(fields):raise ValueError('row')
                out=[_hash(v) for v in row[:3]]+[count(v) for v in row[3:6]]
                if not out[3]<=out[4] or not 0<out[5]<=64:raise ValueError('membership')
                if name=='active':
                    out.append(count(row[6],out[5]))
                else:
                    clocks=row[6:]
                    if (any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in clocks)
                            or clocks!=sorted(clocks)):raise ValueError('clock')
                    out.extend(clocks)
                result[name].append(out)
        if len(result['active'])+result['active_omitted']!=result['active_windows']:raise ValueError('omission')
        if len(result['closed'])+result['closed_omitted']!=min(result['completed_windows'],MAX_CLOSED):
            raise ValueError('omission')
        if result['summary_evictions']!=max(0,result['completed_windows']-MAX_CLOSED):raise ValueError('omission')
        if len(json.dumps(result,allow_nan=False).encode())>4096:raise ValueError('bound')
        return result
    except Exception:
        return dict(state='UNKNOWN',reason='PROOF_PUBLICATION_PROJECTION_UNAVAILABLE',funding_authority=False)
