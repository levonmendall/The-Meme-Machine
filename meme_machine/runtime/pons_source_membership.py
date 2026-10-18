"""Typed, opt-in source-range and watch metadata after native outer COMMIT.

No SQL/provider calls, authority, generic callback registry or economic counting.
Broad scout rows remain nominations until the real native decoders consume them.
"""
import os
import threading

from .journal import digest

MAX_MEMBERS=32768
MAX_ROWS=5000
MAX_STAGES=64
_DOMAIN_TOKEN=object()


def _identity(event):
    from meme_machine.lanes.pons.pons_historical import event_id
    value=event_id(event)
    if len(value)>256:raise ValueError('identity_bound')
    return value


class FactoryDomain:
    """Constructed only from an actual successful native factory replay."""
    def __init__(self,token,owner,replay,result):
        if token is not _DOMAIN_TOKEN or result['source_complete'] is not True:
            raise ValueError('factory_domain_requires_native_replay')
        self.pid=os.getpid();self.binding=owner.owner.source
        self.first=result['first'];self.head=(result['through'],result['through_hash'])
        self.policy=result['policy'];self.provider=result['provider_fingerprint']
        self.chain=result['chain_id'];self.genesis=result['genesis_hash']
        self.events=len(replay.events);self.pending=set();self.resolved=dict(replay.reconciled)
        self.chain_hash=digest(result);self.bridges=0


class PonsSourceMembership:
    def __init__(self,owner):
        self.owner=owner;self.pid=os.getpid();self.lock=threading.Lock();self.loss=None
        self.domain=None;self.broad=None;self.watches={};self.expected=None
        self.watch_census=False;self.native_commits=0

    def unavailable(self,reason='MISSING_NATIVE_WITNESS'):
        self.loss=reason if reason in ('BOUND','CONTENTION','SOURCE_CHANGED','ROLLBACK',
            'MISSING_NATIVE_WITNESS','UNCONFIRMED_COMMIT') else 'MISSING_NATIVE_WITNESS'

    def _apply(self,function):
        if self.loss:return
        if not self.lock.acquire(False):self.unavailable('CONTENTION');return
        try:
            if os.getpid()!=self.pid or self.owner.pid!=self.pid:
                self.unavailable('SOURCE_CHANGED');return
            function()
        except Exception:self.unavailable()
        finally:self.lock.release()

    def install_factory(self,replay,result):
        def apply():
            if replay.owner.owner is not self.owner or replay.pid!=self.pid:
                raise ValueError('foreign_replay')
            self.domain=FactoryDomain(_DOMAIN_TOKEN,self,replay,result)
        self._apply(apply)

    def factory_packet(self,prep,evidence,events):
        if self.loss:return None
        try:
            if (getattr(prep.history,'economic_cohorts',None) is not self.owner
                    or len(events)>MAX_ROWS):raise ValueError('bound')
            from meme_machine.lanes.pons.pons_historical import GRADUATION,number
            rows=tuple((_identity(e),e['topics'][0]==GRADUATION) for e in events)
            e=evidence
            if e['query']!=prep.population_filter():raise ValueError('query')
            previous=e['previous'];end=e['end']
            fields=(e['provider_fingerprint'],e['policy'],e['chain_id'],
                (-1,None) if previous is None else (number(previous),previous['hash']),
                (number(end),end['hash']),len(rows),digest(e),rows)
            return _FactoryCommit(self,fields)
        except Exception:self.unavailable();return None

    def resolved(self,prep,event,token,disposition):
        if self.loss:return None
        try:
            if getattr(prep.history,'economic_cohorts',None) is not self.owner:
                raise ValueError('owner')
            return _ResolutionCommit(self,(_identity(event),token,digest(disposition)))
        except Exception:self.unavailable();return None

    def expect_watches(self,history,rows):
        def apply():
            if getattr(history,'economic_cohorts',None) is not self.owner or len(rows)>MAX_MEMBERS:
                raise ValueError('owner_or_bound')
            expected={r['id']:_watch_fields(r) for r in rows}
            if len(expected)!=len(rows):raise ValueError('duplicate')
            self.expected=expected;self.watch_census=False
        self._apply(apply)

    def seal_watches(self):
        def apply():
            if self.expected is None:raise ValueError('no_census')
            self.watch_census=all(self.watches.get(key)==value for key,value in self.expected.items())
        self._apply(apply)

    def snapshot(self):
        result=dict(contract='NATIVE_SOURCE_AND_WATCH_COMMIT_STAGES',
            canonical_economic_census='UNESTABLISHED',current_curve_consumer_closure='UNESTABLISHED',
            survivor_consumer_closure='UNESTABLISHED',held_membership='UNESTABLISHED',
            full_universe_complete=False,qualification_authority=False)
        if not self.lock.acquire(False):return dict(result,state='UNKNOWN',reason='CONTENTION')
        try:
            domain=self.domain;broad=self.broad
            return dict(result,state='UNKNOWN' if self.loss else 'MEASURING',reason=self.loss,
                native_outer_commits=self.native_commits,
                factory_domain_installed=domain is not None,
                factory_through=None if domain is None else domain.head[0],
                factory_through_hash=None if domain is None else domain.head[1],
                committed_factory_bridges=0 if domain is None else domain.bridges,
                unresolved_factory_graduations=None if domain is None else len(domain.pending),
                factory_chain_sha256=None if domain is None else domain.chain_hash,
                broad_nomination_through=None if broad is None else broad[1],
                broad_nomination_ranges=0 if broad is None else broad[3],
                broad_nomination_chain_sha256=None if broad is None else broad[4],
                broad_nomination_contract='RAW_VARIANTS_NOT_CANONICAL_ECONOMICS',
                expected_watch_members=None if self.expected is None else len(self.expected),
                committed_watch_members=len(self.watches),watch_census_complete=self.watch_census)
        finally:self.lock.release()


def _watch_fields(row):
    grad=row['graduation'];token=row['id'];pool=grad['transition']['market']
    if not 0<len(token)<=64 or not 0<len(pool)<=128:raise ValueError('watch_bound')
    return (pool,grad['block'],grad['block_hash'],grad['at']+7*86400)


class _Commit:
    def __init__(self,owner,fields):self.owner=owner;self.fields=fields
    def capture(self,*_):self.owner.unavailable()
    def committed(self):self.owner._apply(self.apply)


class _FactoryCommit(_Commit):
    def apply(self):
        owner=self.owner;domain=owner.domain
        if domain is None:owner.unavailable();return
        provider,policy,chain,previous,end,count,checksum,rows=self.fields
        if (domain.binding!=owner.owner.source or domain.pid!=os.getpid()
                or (provider,policy,chain)!=(domain.provider,domain.policy,domain.chain)
                or previous!=domain.head or end[0]<=previous[0]):
            owner.unavailable('SOURCE_CHANGED');return
        if domain.events+count>MAX_MEMBERS:owner.unavailable('BOUND');return
        for identity,graduation in rows:
            if graduation:domain.pending.add(identity)
        domain.events+=count;domain.head=end;domain.bridges+=1
        domain.chain_hash=digest([domain.chain_hash,previous,end,count,checksum])
        owner.native_commits+=1


class _ResolutionCommit(_Commit):
    def apply(self):
        domain=self.owner.domain
        if domain is None:self.owner.unavailable();return
        identity,token,checksum=self.fields
        if identity not in domain.pending:
            if domain.resolved.get(identity)==checksum:return
            self.owner.unavailable();return
        domain.pending.remove(identity);domain.resolved[identity]=checksum
        domain.chain_hash=digest([domain.chain_hash,identity,token,checksum]);self.owner.native_commits+=1


class _BroadCommit(_Commit):
    def apply(self):
        owner=self.owner;first,last,head,previous,provider,count,checksum=self.fields
        old=owner.broad
        if old is not None:
            if first!=old[1]+1 or previous!=(old[1],old[2]) or provider!=old[5]:
                owner.unavailable('SOURCE_CHANGED');return
        owner.broad=(first if old is None else old[0],last,head,
            1 if old is None else old[3]+1,digest([None if old is None else old[4],first,last,head,count,checksum]),provider)
        owner.native_commits+=1


class _WatchCommit(_Commit):
    def apply(self):
        owner=self.owner;token,fields,inserted=self.fields
        if len(owner.watches)>=MAX_MEMBERS and token not in owner.watches:
            owner.unavailable('BOUND');return
        # A prior DB row not witnessed in this process cannot be upgraded by an
        # INSERT OR IGNORE no-op. Existing read_pools rows supply that later.
        if not inserted and owner.watches.get(token)!=fields:return
        owner.watches[token]=fields;owner.native_commits+=1


class PonsPlaneObserver:
    """Fixed typed fanout of the SAME native Plane COMMIT result."""
    def __init__(self,owner):self.owner=owner;self.frame=None;self.closed=False
    def begin(self):
        if self.closed or self.frame is not None:self.owner.unavailable();return None
        self.frame=[];return self.frame
    def stage(self,stage):
        if (type(stage) not in (_BroadCommit,_WatchCommit) or stage.owner is not self.owner
                or self.frame is None or len(self.frame)>=MAX_STAGES):
            self.owner.unavailable('BOUND');return
        self.frame.append(stage)
    def finish(self,frame,*,committed,uncertain=False):
        if self.closed or frame is None or self.frame is not frame or uncertain:
            self.owner.unavailable('UNCONFIRMED_COMMIT');self.frame=None;return
        self.frame=None
        if committed:
            for stage in frame:stage.committed()
        elif frame:self.owner.unavailable('ROLLBACK')
    def close(self):
        if self.frame is not None:self.owner.unavailable('UNCONFIRMED_COMMIT')
        self.frame=None;self.closed=True


def plane_observer(plane):
    value=getattr(plane,'_pons_membership_observer',None)
    return value if type(value) is PonsPlaneObserver else None


def bind_plane(plane):
    owner=getattr(getattr(plane,'economic_cohorts',None),'membership',None)
    if owner is None:return
    observer=plane_observer(plane)
    if observer is None:plane._pons_membership_observer=PonsPlaneObserver(owner)
    elif observer.owner is not owner:owner.unavailable()


def history_stage(history,stage):
    if stage is None:return
    frames=getattr(history,'_economic_frames',None)
    if not frames or len(frames[-1])>=MAX_STAGES:stage.owner.unavailable('BOUND');return
    frames[-1].append((stage,None,None,None))
