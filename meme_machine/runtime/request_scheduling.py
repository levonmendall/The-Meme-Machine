"""The existing physical request governor without observer response archives."""
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import os
import time
import urllib.error

priority = ContextVar('market_work_priority',default=10)


def position_work(function):
    @wraps(function)
    def run(*args,**kwargs):
        token=priority.set(0)
        try:return function(*args,**kwargs)
        finally:priority.reset(token)
    return run


def governed_sol_http(function):
    @wraps(function)
    def request(instance,body):
        path=os.environ.get('MM_PROVIDER_GOVERNOR_DB')
        if not path:return function(instance,body)
        from meme_machine.runtime.governor import Governor
        governor=Governor(path)
        calls=body if isinstance(body,list) else [body]
        methods=tuple(row.get('method','unknown') for row in calls)
        level=priority.get()
        if level!=0:level=getattr(instance,'evidence_priority',level)
        deadline=getattr(instance,'evidence_deadline',None)
        remaining=30 if deadline is None else min(30,deadline-time.time())
        from meme_machine.lanes.pump.provider import Unavailable
        try:
            if remaining<=0:raise TimeoutError('evidence_deadline_before_transport')
            governor.acquire('solana',os.environ.get('MM_RUNTIME_LANE','solana'),level,deadline_seconds=remaining,methods=methods)
        except TimeoutError as error:
            # Each namespace keeps its own native provider exception contract.
            native=__import__(instance.__class__.__module__.rsplit('.',1)[0]+'.provider',fromlist=['Unavailable']).Unavailable
            raise native(str(error)) from None
        try:
            result=function(instance,body)
        except urllib.error.HTTPError as error:
            if error.code==429:governor.rate_limited('solana',methods)
            raise
        replies=result if isinstance(result,list) else [result]
        if any((r.get('error') or {}).get('code') in (429,-32005) for r in replies if isinstance(r,dict)):
            governor.rate_limited('solana',methods)
        else:governor.succeeded('solana',methods)
        return result
    return request
