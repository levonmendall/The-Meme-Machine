"""Bounded incremental public log census; never allocation evidence.

The existing scanner still authenticates the entire factory and computes its
exact timestamp boundary. A finalized anchor permits reuse of already fetched
coverage. New factory addresses get the whole current window, not only its tail.
Any missing/changed anchor falls back to the original complete range reader.
"""
from copy import deepcopy
from functools import wraps
import hashlib
import inspect
import threading

from .plane import Plane, canonical, digest, plane_path

KEY = 'ramses_observation_window_v1'
MAX_BYTES = 8 * 1024 * 1024


def _order(event):
    return tuple(int(event[k],16) for k in ('blockNumber','transactionIndex','logIndex'))


class Window:
    def __init__(self, plane, domain, fetch, decode, *, max_rows=5000):
        self.plane,self.domain,self.fetch,self.decode=plane,domain,fetch,decode
        self.max_rows=max_rows
        self.value=None

    def collect(self,rpc,start,end,addresses,progress=None):
        addresses=tuple(addresses)
        old=self.plane.checkpoint_read(KEY)
        if old is not None and old.get('checksum')!=digest({k:v for k,v in old.items() if k!='checksum'}):old=None
        usable=(old is not None and old.get('domain')==self.domain
                and old['start']<=start<=old['end']+1 and old['end']<=end
                and set(old['addresses']).issubset(addresses))
        if usable:
            anchor=rpc.call('eth_getBlockByNumber',[hex(old['end']),False],scope='universe_identity')
            usable=isinstance(anchor,dict) and anchor.get('hash')==old['anchor'] and int(anchor.get('number','-1'),16)==old['end']
        if usable:
            logs=[e for e in old['logs'] if start<=_order(e)[0]<=end]
            logs+=self.fetch(rpc,max(start,old['end']+1),end,old['addresses'],progress)
            old_addresses=set(old['addresses'])
            added=tuple(a for a in addresses if a not in old_addresses)
            logs+=self.fetch(rpc,start,end,added,progress)
            decoded=old.get('decoded',{})
        else:
            logs=self.fetch(rpc,start,end,addresses,progress)
            decoded={}
        # This witness is a reuse fence, not a replacement for complete getLogs
        # pagination. The original reader must complete every requested range.
        anchor=rpc.call('eth_getBlockByNumber',[hex(end),False],scope='universe_identity')
        self.value=dict(domain=self.domain,start=start,end=end,addresses=list(addresses),
                        anchor=anchor.get('hash') if isinstance(anchor,dict) else None,
                        logs=logs,decoded=decoded)
        if not isinstance(anchor,dict) or int(anchor.get('number','-1'),16)!=end or not self.value['anchor']:
            self.value=None
        return logs

    def decoded(self,logs,addresses):
        if self.value is None or logs is not self.value['logs'] or list(addresses)!=self.value['addresses']:
            return self.decode(logs,addresses)
        allowed=set(a.lower() for a in addresses)
        history={};costs=[];retained={}
        for event in sorted(logs,key=_order):
            raw=canonical(event);key=hashlib.sha256(raw.encode()).hexdigest()
            cached=self.value['decoded'].get(key)
            # Do not turn a stale/corrupt projection into an authoritative fact.
            # Raw equality and current membership precede any reuse.
            if cached is None or cached['raw']!=raw or event.get('address','').lower() not in allowed or event.get('removed'):
                by_pool,rows=self.decode([event],addresses)
                cached=dict(raw=raw,history=by_pool,costs=rows)
            for pool,rows in cached['history'].items():history.setdefault(pool,[]).extend(deepcopy(rows))
            costs.extend(deepcopy(cached['costs']));retained[key]=cached
        self.value['decoded']=retained
        if len(logs)<=self.max_rows and len(canonical(self.value).encode())+100<=MAX_BYTES:
            self.value['checksum']=digest(self.value)
            self.plane.checkpoint(KEY,self.value)
        else:
            # Same full-population result; bounded cache is optional. Overload
            # never truncates the comparative population or log coverage.
            self.plane.checkpoint(KEY,None)
        return history,costs


def install(universe):
    """Attach only observation plumbing through the existing runtime adapter."""
    if getattr(universe,'_incremental_observation_attached',False):return
    fetch,decode=universe._batched_logs,universe._decode_economic_logs
    domain=hashlib.sha256((inspect.getsource(fetch)+inspect.getsource(decode)+universe.POLICY_HASH+
                          canonical(universe.load('ramses_pool_implementation')['abi'])).encode()).hexdigest()
    local=threading.local()

    @wraps(fetch)
    def collect(rpc,start,end,addresses,progress=None):
        previous=getattr(local,'window',None)
        if previous is not None:previous.plane.close();local.window=None
        plane=Plane(plane_path(universe.FACTORY_CACHE.with_suffix('.candidates.sqlite')))
        window=Window(plane,domain,fetch,decode,max_rows=universe.MAX_SWAP_LOGS*2)
        try:
            result=window.collect(rpc,start,end,addresses,progress)
        except BaseException:
            plane.close();raise
        local.window=window
        return result

    @wraps(decode)
    def decoded(logs,addresses):
        window=getattr(local,'window',None)
        if window is None:return decode(logs,addresses)
        try:return window.decoded(logs,addresses)
        finally:window.plane.close();local.window=None

    universe._batched_logs=collect;universe._decode_economic_logs=decoded
    universe._incremental_observation_attached=True
