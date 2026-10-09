"""Pons-native authenticated rolling history for Current position management.

Normal sixty-second observations accumulate the approved fifteen-minute add
window. Promotion consumes a small forward delta, never invents an old gap.
The existing Pons plane owns persistence; this module has no provider authority.
"""
from contextvars import ContextVar
from functools import wraps
import json
import threading
import time

from meme_machine.runtime.journal import canonical,digest
from . import BoundaryError

_active=ContextVar('pons_current_history',default=None)

# One background purchase owner, without a queue of optional research. It uses
# the existing provider governor at lower priority than native protection.
_preparation_lock=threading.Lock()
_preparation_executor=None
_preparation_future=None

def active_history():return _active.get()


def prepare_scale_history(history,endpoint,market,candidate,*,key,native_store,identity):
    """Prepare a genuinely missing prefix without occupying a native monitor."""
    global _preparation_executor,_preparation_future
    from concurrent.futures import ThreadPoolExecutor
    from copy import deepcopy
    path=native_store.db.execute('PRAGMA database_list').fetchone()[2]
    if not path:return False
    with _preparation_lock:
        if _preparation_future is not None and not _preparation_future.done():return False
        if _preparation_future is not None:
            # Failed acquisition grants no authority and is retried only after
            # a fresh native eligibility check, never as a permanent token veto.
            try:_preparation_future.result()
            except Exception:pass
        if _preparation_executor is None:
            _preparation_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='pons-scale-history')
        _preparation_future=_preparation_executor.submit(_prepare_scale_prefix,
            history.plane.path,endpoint,market,deepcopy(candidate),key,path,identity)
        return True


def _prepare_scale_prefix(plane_path,endpoint,market,candidate,key,native_path,identity):
    import sqlite3
    from pathlib import Path
    from .provider_admission import decision_work
    from meme_machine.runtime.provider_purchases import attributed_work
    from meme_machine.runtime.robinhood.plane import Plane
    from meme_machine.runtime.robinhood.pons import shared_evidence_domain,durable_cache
    from .pons_selective_acquisition import SelectiveEvidenceContext,_header_search
    from .pons_selective_paper import _read_curve_logs
    from .pons_selective_v4 import collect_v4_activity

    @decision_work(3)
    @attributed_work('scaling_requalification',family='pons',consumer='current')
    def acquire():
        plane=Plane(plane_path);history=CurrentHistory(plane,endpoint)
        db=sqlite3.connect('file:'+str(Path(native_path).resolve())+'?mode=ro',uri=True)
        domain=shared_evidence_domain(endpoint)
        def alive():
            from meme_machine.runtime.stop import requested
            row=db.execute('SELECT body FROM pons_selective_paper WHERE id=?',(identity,)).fetchone()
            if not row or requested.is_set() or shared_evidence_domain(endpoint)!=domain:return False
            p=json.loads(row[0])
            return (p['status']=='open' and p['tokens']>0 and p['market']==market
                and not (p.get('controller_state') or {}).get('pending_action'))
        try:
            if not alive():return False
            old=history.get(market)
            if old is None:return False # normal protection establishes the first short interval
            invalid_key='pons_current_history_invalidated:'+history.domain+':'+market.lower()
            invalidated=plane.checkpoint_read(invalid_key)
            context=SelectiveEvidenceContext(endpoint,cache=durable_cache(plane,domain))
            context.generation_guard=alive;context.deadline=time.monotonic()+60;context.canonical_numbers=True
            anchor=context.call('eth_getBlockByNumber',[hex(old['block']),False],'pons_scale_history')
            if anchor['hash']!=old['block_hash']:raise BoundaryError('pons_current_history_reorg')
            lower=max(0,old['through']-900)
            if old['from_time']<=lower:return True
            # The retained suffix begins at from_time. Only its missing prefix
            # is acquired; its last block is strictly before that boundary.
            end=_header_search(context,old['block'],old['through'],max(0,old['from_time']-1),{old['block']:anchor})
            end_block=int(end['number'],16);end_at=int(end['timestamp'],16)
            if key is None:
                events,_=_read_curve_logs(endpoint,market,end,seconds=max(0,end_at-lower),evidence_context=context)
            else:
                start=_header_search(context,end_block,end_at,lower,{end_block:end})
                tape=collect_v4_activity(endpoint,pool_id=market,key=key,token=candidate['token'],
                    start_block=int(start['number'],16),end_block=end_block,evidence_context=context)
                events=[dict(e,canonical_order=[e['block'],e['transaction_index'],e['log_index']])
                    for e in tape['swaps'] if lower<=e['event_at']<old['from_time']]
            current=history.get(market)
            if (not alive() or current is None or current['from_time']>old['from_time']
                    or plane.checkpoint_read(invalid_key)!=invalidated):return False
            expected={old['block']:old['block_hash'],end_block:end['hash'],current['block']:current['block_hash']}
            members=context.batch([('eth_getBlockByNumber',[hex(n),False]) for n in expected],'pons_scale_history')
            if len(members)!=len(expected) or any(int(h['number'],16)!=n or h['hash']!=bh
                    for (n,bh),h in zip(expected.items(),members)):
                raise BoundaryError('pons_current_history_reorg')
            head=members[list(expected).index(current['block'])]
            history.remember(market,head,events,from_time=lower,expected_frontier=current,
                publication_guard=lambda:plane.checkpoint_read(invalid_key)==invalidated and alive())
            return True
        finally:db.close();plane.close()
    return acquire()


class CurrentHistory:
    def __init__(self,plane,endpoint):
        self.plane=plane;self.domain=digest(endpoint)
        with plane.lock:
            plane.db.executescript('''
                CREATE TABLE IF NOT EXISTS pons_current_history(
                    domain TEXT,curve TEXT,body TEXT,hash TEXT,PRIMARY KEY(domain,curve));
                CREATE TABLE IF NOT EXISTS pons_current_events(
                    domain TEXT,curve TEXT,id TEXT,at INTEGER,body TEXT,hash TEXT,
                    PRIMARY KEY(domain,curve,id));
                CREATE INDEX IF NOT EXISTS pons_current_event_window ON pons_current_events(domain,curve,at);
            ''')

    @staticmethod
    def verified(raw):
        if raw is None:return None
        value=json.loads(raw[0])
        if digest(value)!=raw[1]:raise BoundaryError('pons_current_history_corruption')
        return value

    def get(self,curve):
        with self.plane.lock:
            return self.verified(self.plane.db.execute('SELECT body,hash FROM pons_current_history WHERE domain=? AND curve=?',
                (self.domain,curve.lower())).fetchone())

    def invalidate(self,curve,reason):
        """A fork removes observation authority, never native position state."""
        curve=curve.lower()
        context=getattr(self,'v4_evidence_context',None)
        if context is not None:
            context.cache.invalidate_canonical_aliases();context.block_reads.clear()
        with self.plane.transaction():
            old=self.get(curve)
            if old is None:return
            key='pons_current_history_invalidated:'+self.domain+':'+curve
            previous=self.plane.checkpoint_read(key) or dict(count=0,hash=None)
            events=[self.verified(r) for r in self.plane.db.execute(
                'SELECT body,hash FROM pons_current_events WHERE domain=? AND curve=? ORDER BY id',
                (self.domain,curve))]
            record=dict(count=previous['count']+1,hash=digest([previous['hash'],old,events]),
                reason=reason,old_checkpoint=old,qualification_authority=False)
            self.plane.db.execute('INSERT INTO runtime VALUES(?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body',
                (key,canonical(record)))
            self.plane.db.execute('DELETE FROM pons_current_events WHERE domain=? AND curve=?',(self.domain,curve))
            self.plane.db.execute('DELETE FROM pons_current_history WHERE domain=? AND curve=?',(self.domain,curve))

    def remember(self,curve,header,events,*,from_time,delta_from=None,coverage=None,retain_ids=(),
                 expected_frontier=None,publication_guard=None):
        curve=curve.lower();block=int(header['number'],16);at=int(header['timestamp'],16)
        with self.plane.transaction():
            old=self.get(curve)
            if ((expected_frontier is not None and old!=expected_frontier)
                    or (publication_guard is not None and not publication_guard())):
                raise BoundaryError('pons_current_history_frontier_superseded')
            if from_time>at:raise BoundaryError('pons_current_history_window_identity')
            if old and block<old['block']:
                # A point-in-time candidate may finish after a newer position
                # observation. Its complete window remains its own authority;
                # it cannot move the shared history watermark backwards.
                return old
            if old and block==old['block'] and header['hash']!=old['block_hash']:
                raise BoundaryError('pons_current_history_reorg')
            if delta_from is not None and (old is None or delta_from!=old['block']):
                raise BoundaryError('pons_current_history_delta_identity')
            if coverage is not None:
                first=coverage['first_block']
                if (coverage['last_block']!=block or coverage['end_hash']!=header['hash']
                        or first>block+1 or first<0
                        or (delta_from is not None and first!=delta_from+1)
                        or coverage['events_sha256']!=digest(events)):
                    raise BoundaryError('pons_current_history_coverage_identity')
            lower=min(from_time,old['from_time']) if old and from_time<=old['through'] else from_time
            for event in events:
                if not from_time<=event['event_at']<=at:raise BoundaryError('pons_current_history_future_event')
                identity=event['identity']
                previous=self.verified(self.plane.db.execute('SELECT body,hash FROM pons_current_events WHERE domain=? AND curve=? AND id=?',
                    (self.domain,curve,identity)).fetchone())
                if previous is not None and previous!=event:raise BoundaryError('pons_current_history_event_conflict')
                self.plane.db.execute('INSERT OR IGNORE INTO pons_current_events VALUES(?,?,?,?,?,?)',
                    (self.domain,curve,identity,event['event_at'],canonical(event),digest(event)))
            lower=max(lower,at-900)
            row=dict(from_time=lower,through=at,block=block,block_hash=header['hash'],
                observed_at=time.time(),authority='canonical_receipt_authenticated_complete_log_ranges')
            if coverage is not None:row['last_interval']=coverage
            elif old and block==old['block'] and 'last_interval' in old:row['last_interval']=old['last_interval']
            self.plane.db.execute('INSERT OR REPLACE INTO pons_current_history VALUES(?,?,?,?)',
                (self.domain,curve,canonical(row),digest(row)))
            sql='DELETE FROM pons_current_events WHERE domain=? AND curve=? AND at<?'
            args=[self.domain,curve,lower]
            if retain_ids:
                sql+=' AND id NOT IN ('+','.join('?' for _ in retain_ids)+')';args.extend(retain_ids)
            self.plane.db.execute(sql,args)
        return row

    def v4_window_candidates(self,curve,cutoff):
        """Hot events and the last economic block at/before the original cutoff.

        The caller must authenticate the durable frontier and complete interval.
        One successor header then determines the exact original block boundary,
        including several blocks per second and long empty timestamp gaps.
        """
        with self.plane.lock:
            args=(self.domain,curve.lower(),cutoff)
            older=self.plane.db.execute('''SELECT body,hash FROM pons_current_events
                WHERE domain=? AND curve=? AND at<=?
                ORDER BY at DESC,CAST(json_extract(body,'$.block') AS INTEGER) DESC LIMIT 1''',args).fetchone()
            boundary=self.verified(older)
            sql='SELECT body,hash FROM pons_current_events WHERE domain=? AND curve=? AND (at>?'
            values=list(args)
            if boundary is not None:
                sql+=" OR CAST(json_extract(body,'$.block') AS INTEGER)=?";values.append(boundary['block'])
            rows=[self.verified(r) for r in self.plane.db.execute(sql+')',values)]
        return rows

    def facts(self,curve,header,seconds):
        row=self.get(curve);at=int(header['timestamp'],16);block=int(header['number'],16)
        if (row is None or row['block']!=block or row['block_hash']!=header['hash']
                or row['through']!=at or row['from_time']>max(0,at-seconds)):
            raise BoundaryError('pons_current_history_not_caught_up')
        with self.plane.lock:
            events=[self.verified(r) for r in self.plane.db.execute(
                'SELECT body,hash FROM pons_current_events WHERE domain=? AND curve=? AND at>=? AND at<=?',
                (self.domain,curve.lower(),max(0,at-seconds),at))]
        return sorted(events,key=lambda e:tuple(e.get('canonical_order',(e['event_at'],e['identity']))))

    def maintain(self,now):
        if now<getattr(self,'_maintenance_due',float('-inf')):return
        with self.plane.transaction():
            protected=set()
            for raw, in self.plane.db.execute("SELECT body FROM runtime WHERE key LIKE 'native_position:%'"):
                value=json.loads(raw)
                if value['position']['status']!='settled':protected.add(value['candidate'].rsplit(':',1)[-1].lower())
            for curve,raw,checksum in self.plane.db.execute('SELECT curve,body,hash FROM pons_current_history WHERE domain=?',(self.domain,)).fetchall():
                row=self.verified((raw,checksum))
                if row['observed_at']>=now-900 or curve in protected:continue
                self.plane.db.execute('DELETE FROM pons_current_events WHERE domain=? AND curve=?',(self.domain,curve))
                self.plane.db.execute('DELETE FROM pons_current_history WHERE domain=? AND curve=?',(self.domain,curve))
        self._maintenance_due=now+60


def with_history(function):
    from inspect import isgeneratorfunction
    if isgeneratorfunction(function):
        @wraps(function)
        def steps(endpoint,evaluation,*args,**kwargs):
            path=evaluation.get('candidate_plane_path')
            if not path:return (yield from function(endpoint,evaluation,*args,**kwargs))
            from meme_machine.runtime.robinhood.plane import Plane
            plane=Plane(path);history=CurrentHistory(plane,endpoint);token=_active.set(history)
            try:return (yield from function(endpoint,evaluation,*args,**kwargs))
            finally:_active.reset(token);plane.close()
        return steps
    @wraps(function)
    def wrapped(endpoint,evaluation,*args,**kwargs):
        path=evaluation.get('candidate_plane_path')
        if not path:return function(endpoint,evaluation,*args,**kwargs)
        from meme_machine.runtime.robinhood.plane import Plane
        plane=Plane(path);history=CurrentHistory(plane,endpoint);token=_active.set(history)
        try:return function(endpoint,evaluation,*args,**kwargs)
        finally:_active.reset(token);plane.close()
    return wrapped
