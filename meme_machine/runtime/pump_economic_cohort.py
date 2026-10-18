"""Opt-in native rolling-program cohort adapter; no economic authority.

Only the original prepared source, native store, full binding iteration and
verified delivery ACK invoke these hooks. The source's own linked-child proofs
close windows. No database query, provider operation or event body is retained.
"""
from collections import deque
import math
import os
import time

from .economic_cohort import EconomicCohorts,checksum,MAX_IDENTITIES,MAX_OBLIGATIONS,MAX_BYTES

WINDOW_BLOCKS=8


class PumpEconomicCohorts:
    def __init__(self,run_identity,endpoint):
        from ..solana_selective_history import FAMILIES
        self.scopes=tuple(FAMILIES[family] for family in ('pump','pumpswap'))
        self.meter=EconomicCohorts('pump',dict(source_pid=os.getpid(),run_identity=run_identity,
            endpoint_sha256=endpoint))
        from .native_proof_publication import NativeProofPublications
        self.proof_publications=NativeProofPublications(self.meter.binding_hash)
        self.sessions={};self.frames={};self.windows={};self.source_closed=deque(maxlen=16)
        self.source_evictions=0;self.closed_upper=None;self.head=None;self.head_pending=None

    def control_head(self,frame):
        """Already joined FINALIZED control header, before its existing queue."""
        try:
            block=frame.update.block;wall=time.time();mono=time.monotonic()
            if (not block.HasField('block_time') or block.block_time.timestamp<=0
                    or not 0<block.slot<2**63 or not block.blockhash or not block.parent_blockhash
                    or not all(math.isfinite(v) for v in (wall,mono,frame.seen))):
                raise ValueError('head')
            current=dict(slot=block.slot,parent_slot=block.parent_slot,
                block_sha256=checksum(block.blockhash),parent_sha256=checksum(block.parent_blockhash),
                market_wall=block.block_time.timestamp,received_wall=frame.seen,
                observed_wall=wall,observed_monotonic=mono)
            previous=self.head_pending
            self.head_pending=(block.slot,block.blockhash,current)
            if previous is not None and (block.parent_slot,block.parent_blockhash)==previous[:2]:
                self.head=dict(previous[2],linked_child_slot=block.slot,
                    linked_child_sha256=checksum(block.blockhash),linked_child_market_wall=block.block_time.timestamp,
                    observed_wall=wall,observed_monotonic=mono)
        except Exception:self.unavailable('SOURCE_CLOSURE_UNAVAILABLE')

    def unavailable(self,reason='NATIVE_BOUNDARY_UNAVAILABLE'):self.meter.unavailable(reason)

    def session(self,identity,lower,addresses):
        try:
            from ..solana_rolling_history import program_scope
            from ..solana_selective_history import PROGRAMS
            if (type(identity) is not str or not 0<len(identity)<=64 or type(lower) is not int
                    or not 0<lower<2**63 or addresses!={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}):
                self.unavailable('SOURCE_CLOSURE_UNAVAILABLE');return
            # The native reconnect retains unavailable prospective prefixes.
            # Never merge overlapping replay cohorts or relabel that gap as a
            # single continuous economic denominator in this measurement epoch.
            if self.sessions:self.unavailable('GAP');return
            self.sessions[identity]=dict(lower=lower,previous=None,window=None,count=0,index=0)
        except Exception:self.unavailable('SOURCE_CLOSURE_UNAVAILABLE')

    def prepared(self,identity,frames,products):
        if self.meter.loss:return
        try:
            session=self.sessions[identity]
            for frame,product in zip(frames,products,strict=True):
                block=frame.update.block;slot=block.slot
                if not block.HasField('block_time') or block.block_time.timestamp<=0:
                    self.unavailable('SOURCE_CLOSURE_UNAVAILABLE');return
                if slot<session['lower']:continue # Explicit initial replay prefix.
                if self.closed_upper is not None and slot<=self.closed_upper:continue
                key=(identity,slot)
                if key in self.frames:continue
                previous=session['previous']
                if previous is not None and (block.parent_slot,block.parent_blockhash)!=previous:
                    self.unavailable('GAP');return
                if session['count']==WINDOW_BLOCKS:
                    old=self.windows[session['window']];old['upper']=slot-1
                    old['linked_child_market_wall']=block.block_time.timestamp
                    session['window']=None;session['count']=0
                if session['window'] is None:
                    cohort=identity+':'+str(session['index']);session['index']+=1
                    session['window']=cohort
                    self.windows[cohort]=dict(lower=slot,upper=None,frames=set(),proofs={},
                        lower_market_wall=block.block_time.timestamp,linked_child_market_wall=None)
                    self.meter.open(cohort,self.scopes)
                cohort=session['window'];window=self.windows[cohort]
                entries=tuple((p.record.scope,p.record.identity,p.economic_hash,p.record.slot,p.record.observed_at)
                    for p in product.rows)
                self.meter.arrivals(cohort,entries)
                if self.meter.loss:return
                self.frames[key]=dict(cohort=cohort,entries=entries,committed=False)
                window['frames'].add(key);session['count']+=1
                session['previous']=(slot,block.blockhash)
                if len(self.frames)>WINDOW_BLOCKS*8+1 or len(self.windows)>8:
                    self.unavailable('BOUND');return
        except Exception:self.unavailable()

    def stage(self,identity,frames):
        return _Stage(self,identity,frames)

    def complete(self,stage):
        if self.meter.loss:return
        try:
            for key in stage.frames:
                frame=self.frames.get(key)
                if frame is None:continue
                rows=stage.rows.get(key,[])
                self.meter.committed(frame['cohort'],rows,stage.fanout.get(key,[]),
                    fanout_complete=stage.completed.get(key,[]))
                frame['committed']=True
            for proof_id,scope,lo,hi,witness in stage.proofs:
                for identity,window in list(self.windows.items()):
                    if hi<window['lower'] or window['upper'] is not None and lo>window['upper']:continue
                    values=window['proofs'].setdefault(scope,[]);value=(lo,hi,witness,proof_id)
                    if value not in values:
                        if len(values)>=32:self.unavailable('BOUND');return
                        values.append(value)
                    self.proof_publications.register(proof_id,witness)
            self._seal()
        except Exception:self.unavailable()

    def _seal(self):
        from ..solana_rolling_history import program_scope
        for identity,window in list(self.windows.items()):
            lower,upper=window['lower'],window['upper']
            if upper is None or not all(self.frames[key]['committed'] for key in window['frames']):continue
            complete=True;proof=[];proof_ids=set()
            for scope in (program_scope('pump'),program_scope('pumpswap')):
                cursor=lower
                for lo,hi,witness,proof_id in sorted(window['proofs'].get(scope,())):
                    if lo>cursor:break
                    if hi>=cursor:
                        cursor=hi+1;proof.append((scope,lo,hi,witness));proof_ids.add(proof_id)
                if cursor<=upper:complete=False
            if not complete:continue
            if self.closed_upper is not None and lower!=self.closed_upper+1:
                self.unavailable('GAP');return
            source_digest=checksum(proof)
            census=sorted({entry[:4] for key in window['frames'] for entry in self.frames[key]['entries']})
            self.meter.seal(identity,lower,upper,source_digest,complete=True,
                expected_economics=(len(census),checksum(census)))
            if self.meter.loss:return
            self.proof_publications.expect(identity,lower,upper,source_digest,tuple(sorted(proof_ids)))
            if len(self.source_closed)==self.source_closed.maxlen:self.source_evictions+=1
            self.source_closed.append(dict(cohort_sha256=checksum(identity),lower=lower,upper=upper,
                source_sha256=source_digest,lower_market_wall=window['lower_market_wall'],
                linked_child_market_wall=window['linked_child_market_wall']))
            self.closed_upper=upper
            # Source metadata can be freed at source closure. Economic/fanout
            # identities remain in the bounded meter until actual FULL ACK.
            for key in window['frames']:self.frames.pop(key,None)
            del self.windows[identity]
        self._retain_proof_metadata()

    def _retain_proof_metadata(self):
        self.proof_publications.retain({value[3] for window in self.windows.values()
            for values in window['proofs'].values() for value in values})

    def published_proofs(self,rows):
        self.proof_publications.published(rows)
        self._retain_proof_metadata()

    def acknowledge(self,rows):self.meter.acknowledged(rows)
    def snapshot(self):
        result=self.meter.snapshot()
        result.update(source_closed=[dict(row) for row in self.source_closed],source_summary_evictions=self.source_evictions,
            source_clock_contract='AUTHENTICATED_BLOCK_TIME_SECONDS_NOT_KERNEL_CREATION_TIME',
            head_contract='OBSERVED_LINKED_FINALIZED_HEADERS_NOT_DURABLE_CONTROL_OR_UNSEEN_TIP')
        result['proof_publication']=self.proof_publications.snapshot()
        head=self.head
        if head is not None:
            head=dict(head);wall=time.time();mono=time.monotonic()
            head.update(sample_wall=wall,sample_monotonic=mono,
                observation_age_seconds=mono-head['observed_monotonic'],
                market_age_seconds=wall-head['market_wall'],
                wall_monotonic_delta_seconds=(wall-head['observed_wall'])-(mono-head['observed_monotonic']))
        result['observed_finalized_head']=head
        return result


def projection(value):
    """Fixed public schema from the already-read native_streams health row.

    No arbitrary text, event identities, provider fields or output-bound growth.
    Omission/overflow is UNKNOWN; this function does not authenticate source.
    """
    try:
        import json
        from .economic_cohort import _hash,MAX_ACTIVE,MAX_IDENTITIES,MAX_OBLIGATIONS,MAX_BYTES,MAX_SUMMARIES,MAX_COHORTS
        def count(v,maximum=2**63-1):
            if type(v) is not int or not 0<=v<=maximum:raise ValueError('count')
            return v
        def number(v,nullable=False):
            if nullable and v is None:return None
            if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('clock')
            return v
        def select(row,counts=(),hashes=(),numbers=()):
            if type(row) is not dict or len(row)>32:raise ValueError('shape')
            return dict([(k,count(row[k])) for k in counts]+[(k,_hash(row[k])) for k in hashes]+
                [(k,number(row[k],True)) for k in numbers])
        if (type(value) is not dict or len(value)>32 or value.get('schema')!='native-economic-cohort-v1'
                or value.get('lane')!='pump' or value.get('state') not in ('MEASURING','UNKNOWN')):
            raise ValueError('shape')
        fixed=dict(delivery_contract='SOLANA_CONSUMER_FULL_COMMIT_AND_SOURCE_ACK',
            classification_contract='NATIVE_CANONICAL_INSERT_NOT_GLOBAL_FIRST_ARRIVAL',
            processing_stage='SOURCE_CANONICAL_AND_HISTORY_DELIVERY_NOT_STRATEGY_OR_PROOF_PUBLICATION',
            full_market_rate='UNKNOWN_REQUIRES_CONTIGUOUS_SOURCE_AND_FRESH_HEAD_CENSUS',
            historical_completion=False,readiness_authority=False,funding_authority=False,
            source_clock_contract='AUTHENTICATED_BLOCK_TIME_SECONDS_NOT_KERNEL_CREATION_TIME',
            head_contract='OBSERVED_LINKED_FINALIZED_HEADERS_NOT_DURABLE_CONTROL_OR_UNSEEN_TIP')
        if any(type(value.get(k)) is not type(v) or value.get(k)!=v for k,v in fixed.items()):raise ValueError('contract')
        reason=value.get('reason')
        if reason not in (None,'CONTENTION','INVALID_OR_UNAVAILABLE_MEASUREMENT','NATIVE_BOUNDARY_UNAVAILABLE',
                'BOUND','GAP','TRANSACTION_FAILED','SOURCE_CLOSURE_UNAVAILABLE','UNSUPPORTED_PATH'):
            raise ValueError('reason')
        result=select(value,counts=('active_cohorts','active_identities','active_fanout','pending_full_ack',
            'completed_cohorts','summary_evictions','source_summary_evictions'),
            hashes=('binding_sha256','cumulative_summary_sha256'))
        bounds=dict(active=MAX_ACTIVE,identities=MAX_IDENTITIES,obligations=MAX_OBLIGATIONS,
            cohorts=MAX_COHORTS,metadata_bytes=MAX_BYTES)
        if value.get('bounds')!=bounds:raise ValueError('bounds')
        active=value.get('active');closed=value.get('closed');source=value.get('source_closed')
        if (type(active) is not list or len(active)>MAX_ACTIVE or type(closed) is not list
                or len(closed)>MAX_SUMMARIES or type(source) is not list or len(source)>16):raise ValueError('bound')
        result.update(fixed,schema='native-economic-cohort-v1',lane='pump',state=value['state'],reason=reason,
            bounds=bounds,active=[],closed=[],source_closed=[])
        for row in active:
            r=select(row,counts=('unique_economics','canonical_publications','native_new','native_replay'),
                hashes=('cohort_sha256','scope_sha256','economic_sha256','publication_sha256'))
            if (type(row.get('source_complete')) is not bool or r['native_new']+r['native_replay']!=r['canonical_publications']
                    or not r['canonical_publications']<=r['unique_economics']<=MAX_IDENTITIES):raise ValueError('membership')
            r['source_complete']=row['source_complete']
            for k in ('lower','upper'):r[k]=None if row.get(k) is None else count(row[k])
            r['source_sha256']=None if row.get('source_sha256') is None else _hash(row['source_sha256'])
            result['active'].append(r)
        if (result['active_cohorts']!=len(active) or result['active_identities']!=sum(r['unique_economics'] for r in result['active'])
                or result['active_fanout']>MAX_OBLIGATIONS or result['pending_full_ack']>result['active_fanout']):
            raise ValueError('membership')
        for row in closed:
            r=select(row,counts=('lower','upper','unique_economics','new_canonical','replay_canonical',
                'fanout_obligations','verified_full_acks'),hashes=('cohort_sha256','source_sha256','economic_sha256','fanout_sha256'),
                numbers=('original_available_wall_min','original_available_wall_max','first_observed_monotonic',
                    'last_commit_observed_monotonic','completion_observed_monotonic'))
            if (row.get('state')!='CLOSED_COHORT_RECONCILED' or row.get('fanout_scope')!=
                    'COMPLETE_BINDINGS_AT_EACH_CANONICAL_COMMIT_NOT_FUTURE_MEMBERSHIP'
                    or r['lower']>r['upper'] or r['new_canonical']+r['replay_canonical']!=r['unique_economics']
                    or r['unique_economics']>MAX_IDENTITIES or r['fanout_obligations']>MAX_OBLIGATIONS
                    or r['verified_full_acks']!=r['fanout_obligations']):raise ValueError('membership')
            clocks=[r[k] for k in ('first_observed_monotonic','last_commit_observed_monotonic','completion_observed_monotonic')]
            if any(v is None for v in clocks) or clocks!=sorted(clocks):raise ValueError('clock')
            r.update(state='CLOSED_COHORT_RECONCILED',fanout_scope=row['fanout_scope']);result['closed'].append(r)
        for row in source:
            r=select(row,counts=('lower','upper','lower_market_wall','linked_child_market_wall'),
                hashes=('cohort_sha256','source_sha256'))
            if r['lower']>r['upper']:raise ValueError('interval')
            result['source_closed'].append(r)
        from .native_proof_publication import projection as proof_projection
        result['proof_publication']=proof_projection(value['proof_publication'],result['binding_sha256'])
        head=value.get('observed_finalized_head');result['observed_finalized_head']=None
        if head is not None:
            result['observed_finalized_head']=select(head,counts=('slot','parent_slot','market_wall',
                'linked_child_slot','linked_child_market_wall'),hashes=('block_sha256','parent_sha256','linked_child_sha256'),
                numbers=('received_wall','observed_wall','observed_monotonic',
                    'sample_wall','sample_monotonic','observation_age_seconds','market_age_seconds','wall_monotonic_delta_seconds'))
        if len(json.dumps(result,allow_nan=False).encode())>24*1024:
            # Preserve the original 24-KiB envelope and every original field.
            # Only optional proof sample vectors may be omitted; all validated
            # population counts, digests and explicit omission counts remain.
            proof=result['proof_publication']
            if proof.get('schema')=='native-source-proof-publication-v1':
                proof['active']=[];proof['active_omitted']=proof['active_windows']
                proof['closed']=[];proof['closed_omitted']=min(proof['completed_windows'],16)
        if len(json.dumps(result,allow_nan=False).encode())>24*1024:raise ValueError('bound')
        return result
    except Exception:
        return dict(state='UNKNOWN',reason='ECONOMIC_COHORT_PROJECTION_UNAVAILABLE',funding_authority=False)


class _Stage:
    """One real canonical transaction's disposable metadata, never a spool."""
    def __init__(self,owner,identity,frames):
        self.owner=owner;self.frames=tuple((identity,f.update.block.slot) for f in frames)
        self.keys={}
        for key in self.frames:
            for entry in owner.frames.get(key,{}).get('entries',()):
                if len(self.keys)>=MAX_IDENTITIES:owner.unavailable('BOUND');break
                self.keys[entry[:2]]=key
        self.rows={};self.fanout={};self.completed={};self.proofs=[];self.count=0;self.bytes=0

    def canonical(self,row,content_hash,available,new):
        if self.owner.meter.loss:return
        key=self.keys.get((row.scope,row.identity))
        if key is not None:
            self.rows.setdefault(key,[]).append((row.scope,row.identity,content_hash,row.slot,available,bool(new)))

    def obligation(self,identity,economic_identity,source_hash,consumer):
        if self.owner.meter.loss:return
        key=self.keys.get(economic_identity)
        if key is not None:
            self.count+=1;self.bytes+=len(identity)+sum(map(len,economic_identity))+len(source_hash)+len(consumer)
            if self.count>MAX_OBLIGATIONS or self.bytes>MAX_BYTES:self.owner.unavailable('BOUND');return
            self.fanout.setdefault(key,[]).append((identity,*economic_identity,source_hash,consumer))

    def fanout_complete(self,row,count,digest):
        if self.owner.meter.loss:return
        key=self.keys.get((row.scope,row.identity))
        if key is not None:
            self.completed.setdefault(key,[]).append((row.scope,row.identity,count,digest))

    def proof(self,proof,identity):
        proof.validate()
        from ..solana_evidence_plane import digest
        if identity!=digest([proof.scope,proof.lower_slot,proof.upper_slot,proof.witness]):
            self.owner.unavailable();return
        if len(self.proofs)>=16:self.owner.unavailable('BOUND');return
        self.proofs.append((identity,proof.scope,proof.lower_slot,proof.upper_slot,
            checksum([proof.scope,proof.lower_slot,proof.upper_slot,proof.source,
                proof.endpoint_identity,proof.witness,proof.observed_at])))


def canonical(writer,row,content_hash,available,new):
    stage=getattr(writer,'_economic_cohort_stage',None)
    if stage is not None:
        try:stage.canonical(row,content_hash,available,new)
        except Exception:stage.owner.unavailable()


def obligation(writer,identity,economic_identity,source_hash,consumer):
    stage=getattr(writer,'_economic_cohort_stage',None)
    if stage is not None:
        try:stage.obligation(identity,economic_identity,source_hash,consumer)
        except Exception:stage.owner.unavailable()
