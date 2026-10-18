"""Opt-in observations of real Pons decoding and native history COMMITs.

Raw scout variants are not economic arrivals. These hooks use the original
receipt/header/ABI-validated curve trades and V4 swaps, and the native history's
existing prior-row test. They add no query, provider call or financial authority.
Source universe and consumer closure are deliberately unestablished in this
first stage: native history publication is not a Solana FULL/ACK contract.
"""
from contextlib import contextmanager
import os
import threading

from .economic_cohort import EconomicCohorts,checksum

MAX_STAGE_ROWS=2048
MAX_PENDING=64
MAX_PENDING_ROWS=64*256


class PonsEconomicCohorts:
    def __init__(self,run_identity,endpoint,*,native_owner=None):
        from .robinhood.pons import shared_evidence_domain
        self.source=shared_evidence_domain(endpoint)
        self.native_owner=native_owner
        if native_owner is not None:
            from meme_machine.operational.normal_pons_boot import require_pons_owner_context
            require_pons_owner_context(native_owner)
        self.pid=os.getpid();self.lock=threading.Lock();self.pending={}
        self.group=threading.local()
        self.meter=EconomicCohorts('pons',dict(source_pid=self.pid,
            run_identity=run_identity,configured_provider_domain=self.source,
            source_generation='UNESTABLISHED',
            source_generation_contract='NOT_ISSUED_BY_PROVIDER_DOMAIN',
            native_owner_identity_sha256='UNISSUED' if native_owner is None else native_owner.identity_sha256,
            consumer_contract='current_curve_history_and_survivor_v4_history'))
        self.publications=dict(current_curve_history=0,survivor_v4_history=0)
        from .pons_factory_census import PonsFactoryCensus
        self.factory=PonsFactoryCensus(self)
        from .pons_source_membership import PonsSourceMembership
        self.membership=PonsSourceMembership(self)

    def unavailable(self,reason='NATIVE_BOUNDARY_UNAVAILABLE'):
        self.meter.unavailable(reason)

    def require_owner(self):
        if self.pid!=os.getpid():raise ValueError('native_owner_process_changed')
        if self.native_owner is not None:
            from meme_machine.operational.normal_pons_boot import require_pons_owner_context
            require_pons_owner_context(self.native_owner)

    def _stage(self,consumer,scope,lower,upper,end_hash,raw,rows,available):
        if self.meter.loss:return None
        if os.getpid()!=self.pid or len(raw)>MAX_STAGE_ROWS or len(rows)>MAX_STAGE_ROWS:
            self.unavailable('BOUND');return None
        # This mapping is made only at the original authenticated decoder. The
        # normalized identity alone omits blockHash and cannot authenticate forks.
        by_id={f"{int(e['blockNumber'],16)}:{e['transactionHash']}:{int(e['logIndex'],16)}":e for e in raw}
        entries={}
        for row in rows:
            event=by_id[row['identity']]
            identity=event['blockHash']+':'+event['transactionHash']+':'+str(int(event['logIndex'],16))
            entries[row['identity']]=(scope,identity,checksum(row),int(event['blockNumber'],16),available)
        if len(entries)!=len(rows):raise ValueError('economic_cohort_duplicate_normalized_identity')
        cid=consumer+':'+checksum([self.source,scope,lower,upper,end_hash])
        self.meter.open(cid,(scope,));self.meter.arrivals(cid,tuple(entries.values()))
        return _Stage(self,cid,consumer,entries,lower,upper,
            checksum([self.source,scope,lower,upper,end_hash,sorted(r[:4] for r in entries.values())]))

    def current(self,curve,header,raw,rows,coverage,available):
        try:
            upper=int(header['number'],16)
            if (coverage is None or coverage.get('complete') is not True
                    or coverage['through_block']!=upper or coverage['through_hash']!=header['hash']):
                self.unavailable('SOURCE_CLOSURE_UNAVAILABLE');return None
            return self._stage('current_curve_history','pons:curve:'+curve.lower(),
                coverage['from_block'],upper,header['hash'],raw,rows,available)
        except Exception:self.unavailable();return None

    def prepared_v4(self,pool,token,first,last,raw,rows,available):
        if self.meter.loss:return
        if not self.lock.acquire(False):self.unavailable();return
        try:
            if (os.getpid()!=self.pid or len(raw)>MAX_STAGE_ROWS or len(rows)>MAX_STAGE_ROWS
                    or len(self.pending)>=MAX_PENDING
                    or sum(len(value[3]) for value in self.pending.values())+len(rows)>MAX_PENDING_ROWS):
                self.unavailable('BOUND');return
            # Keep only bounded identity/semantic metadata. No economic body or
            # receipt is retained by this side channel after the native return.
            by_id={f"{int(e['blockNumber'],16)}:{e['transactionHash']}:{int(e['logIndex'],16)}":e for e in raw}
            entries={}
            for row in rows:
                event=by_id[row['identity']]
                identity=event['blockHash']+':'+event['transactionHash']+':'+str(int(event['logIndex'],16))
                native=dict(id=row['identity'],at=row['event_at'],group=row['group'],buy=row['side']=='buy',
                    quote=row['quote'],tokens=row['tokens'],authenticated=True,block=row['block'],
                    transaction_index=row.get('transaction_index'),log_index=row.get('log_index'))
                entries[row['identity']]=(identity,checksum(row),int(event['blockNumber'],16),available,checksum(native))
            if len(entries)!=len(rows):raise ValueError('economic_cohort_duplicate_normalized_identity')
            group=getattr(self.group,'current',None)
            if group is not None and ((pool,token) not in group[2] or (first,last)!=group[:2]):
                raise ValueError('economic_cohort_group_identity')
            self.pending[(token,last)]=(pool,first,last,entries,group)
        except Exception:self.unavailable()
        finally:self.lock.release()

    def survivor(self,row,end,header,tape):
        if self.meter.loss:return None
        if not self.lock.acquire(False):self.unavailable();return None
        try:
            prepared=self.pending.pop((row['id'],end),None)
            if prepared is None:
                self.unavailable('UNSUPPORTED_PATH');return None
            pool,first,last,entries,group=prepared
            if pool!=row['graduation']['transition']['market'] or int(header['number'],16)!=end:
                raise ValueError('economic_cohort_native_frontier')
            selected={};expected={}
            for event in tape['swaps']:
                identity,event_hash,block,available,native_hash=entries[event['identity']]
                if checksum(event)!=event_hash or block<=row['block']:
                    raise ValueError('economic_cohort_native_subset')
                selected[event['identity']]=('pons:pool:'+pool,identity,event_hash,block,available)
                expected[event['identity']]=native_hash
            scope='pons:pool:'+pool;lower=max(first,row['block']+1)
            scopes=(scope,);key=scope
            if group is not None:
                lower=first;scopes=tuple('pons:pool:'+p for p,_ in group[2]);key=group
            cid='survivor_v4_history:'+checksum([self.source,key,lower,last,header['hash']])
            self.meter.open(cid,scopes);self.meter.arrivals(cid,tuple(selected.values()))
            return _Stage(self,cid,'survivor_v4_history',selected,lower,last,
                checksum([self.source,key,lower,last,header['hash']]),expected)
        except Exception:self.unavailable();return None
        finally:self.lock.release()

    def snapshot(self):
        try:self.require_owner()
        except Exception:self.unavailable()
        result=self.meter.snapshot()
        if not self.lock.acquire(False):
            result.update(state='UNKNOWN',reason='CONTENTION');return result
        try:
            result.update(native_history_transactions=dict(self.publications),
                factory_domain=self.factory.snapshot(),
                source_membership=self.membership.snapshot(),
                native_owner_provenance='UNISSUED' if self.native_owner is None else 'SEALED_SUPERVISOR_PONS_OWNER_ONLY',
                native_owner_identity_sha256=None if self.native_owner is None else self.native_owner.identity_sha256,
                configured_pool_universe='UNKNOWN',native_generation_dispositions='UNEXERCISED',
                current_held_v4_history='UNEXERCISED',source_full_ack='NOT_A_PONS_CONTRACT')
            return result
        finally:self.lock.release()


class _Stage:
    def __init__(self,owner,cid,consumer,entries,lower,upper,witness,expected=None):
        self.owner=owner;self.cid=cid;self.consumer=consumer;self.entries=entries
        self.lower=lower;self.upper=upper;self.witness=witness;self.captured={}
        self.expected=expected if expected is not None else {key:row[2] for key,row in entries.items()}

    def capture(self,identity,new,native_hash):
        try:
            row=self.entries[identity]
            if type(new) is not bool or self.expected[identity]!=native_hash:raise ValueError('classification')
            self.captured[identity]=(*row,new)
        except Exception:self.owner.unavailable()

    def committed(self):
        try:
            if os.getpid()!=self.owner.pid:self.owner.unavailable();return
            if set(self.captured)!=set(self.entries):
                self.owner.unavailable('GAP');return
            self.owner.meter.committed(self.cid,tuple(self.captured.values()),())
            # Never infer configured-pool/source/delivery closure from a single
            # authenticated range or even an empty set of fanout obligations.
            self.owner.meter.seal(self.cid,self.lower,self.upper,self.witness,complete=False)
            if not self.owner.lock.acquire(False):self.owner.unavailable();return
            try:self.owner.publications[self.consumer]+=1
            finally:self.owner.lock.release()
        except Exception:self.owner.unavailable()


@contextmanager
def survivor_transaction(history):
    """Observe the original PonsHistory transaction, including savepoints."""
    owner=getattr(history,'economic_cohorts',None)
    if owner is None:
        yield;return
    frames=getattr(history,'_economic_frames',None)
    if frames is None:frames=[];history._economic_frames=frames
    if (not frames and history.db.in_transaction) or len(frames)>=8:
        owner.unavailable('UNSUPPORTED_PATH');yield;return
    stage=getattr(history,'_economic_stage',None)
    frame=[] if stage is None else [(stage,None,None,None)]
    frames.append(frame)
    try:
        yield
    except BaseException:
        try:
            from .pons_source_membership import history_rollback
            history_rollback(frame)
        except Exception:pass
        owner.unavailable('TRANSACTION_FAILED');raise
    else:
        try:
            if len(frames)>1:
                if len(frames[-2])+len(frame)>MAX_STAGE_ROWS:owner.unavailable('BOUND')
                else:frames[-2].extend(frame)
            else:
                # The original outer COMMIT has returned before publication.
                stages={}
                for stage,identity,new,native_hash in frame:
                    if identity is not None:stage.capture(identity,new,native_hash)
                    stages[id(stage)]=stage
                for stage in stages.values():stage.committed()
        except Exception:owner.unavailable()
    finally:frames.pop()


@contextmanager
def survivor_publication(history,stage):
    previous=getattr(history,'_economic_event_observer',None)
    previous_stage=getattr(history,'_economic_stage',None)
    if stage is None:
        yield;return
    def record(identity,new,event):
        try:
            frames=getattr(history,'_economic_frames',())
            if not frames or len(frames[-1])>=MAX_STAGE_ROWS:
                stage.owner.unavailable('BOUND');return
            frames[-1].append((stage,identity,new,checksum(event)))
        except Exception:stage.owner.unavailable()
    history._economic_event_observer=record
    history._economic_stage=stage
    try:yield
    finally:
        history._economic_event_observer=previous
        history._economic_stage=previous_stage


@contextmanager
def current_publication(stage):
    try:yield
    except BaseException:
        if stage is not None:stage.owner.unavailable('TRANSACTION_FAILED')
        raise
    else:
        if stage is not None:
            try:stage.committed()
            except Exception:stage.owner.unavailable()


def capture(stage,identity,new,event):
    if stage is not None:
        try:stage.capture(identity,new,checksum({k:v for k,v in event.items() if k!='canonical_order'}))
        except Exception:stage.owner.unavailable()


def current(plane,curve,header,raw,rows,coverage,available):
    owner=getattr(plane,'economic_cohorts',None)
    if owner is None:return None
    try:return owner.current(curve,header,raw,rows,coverage,available)
    except Exception:owner.unavailable();return None


def prepared_v4(owner,pool,token,first,last,raw,rows,available):
    if owner is not None:
        try:owner.prepared_v4(pool,token,first,last,raw,rows,available)
        except Exception:owner.unavailable()


@contextmanager
def shared_v4(owner,markets,first,last):
    """One original <=64-market acquisition is one diagnostic cohort.

    Every pool still traverses its original decoder and its own real native
    history COMMIT. This is configured turn membership, not a global universe.
    """
    if owner is None:
        yield;return
    previous=getattr(owner.group,'current',None)
    try:
        members=tuple(sorted((m['pool_id'],m['token']) for m in markets))
        if (previous is not None or not 1<=len(members)<=64 or len(set(members))!=len(members)):
            raise ValueError('economic_cohort_group_bound')
        owner.group.current=(first,last,members)
    except Exception:owner.unavailable()
    try:yield
    except BaseException:
        owner.unavailable();raise
    finally:owner.group.current=previous


def survivor(owner,row,end,header,tape):
    if owner is None:return None
    try:return owner.survivor(row,end,header,tape)
    except Exception:owner.unavailable();return None


def validated(owner,endpoint):
    if owner is None:return None
    try:
        from .robinhood.pons import shared_evidence_domain
        if type(owner) is PonsEconomicCohorts and owner.pid==os.getpid() and owner.source==shared_evidence_domain(endpoint):
            owner.require_owner()
            return owner
        owner.unavailable()
    except Exception:
        try:owner.unavailable()
        except Exception:pass
    return None
