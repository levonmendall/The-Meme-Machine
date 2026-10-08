"""Rotate exhausted local RPC sessions without bypassing chain authentication."""
from . import BoundaryError


class PositionSessions:
    def __init__(self,current,factory,on_rotate):
        # The lifecycle receives its already authenticated entry session.
        self._current=current
        self._factory=factory
        self._on_rotate=on_rotate
        self._authenticated=True
        self._authentication_attempt=0

    def __getattr__(self,name):
        return getattr(self._current,name)

    def _ensure_authenticated(self):
        if self._authenticated:return
        self._authentication_attempt+=1
        row=dict(reason='session_authentication_recovery',method='eth_chainId',
                 scope='connectivity',previous_used=self._current.used,
                 local_session_rotation=False,provider_retry=True,
                 authentication_attempt=self._authentication_attempt,authenticated=False)
        try:
            self._current.verify_chain()
            self._authenticated=True
            row['authenticated']=True
        except BoundaryError as exc:
            row['boundary']=str(exc)
            raise
        finally:
            # The current session remains current; do not count its telemetry
            # twice or create a new session to evade an authentication failure.
            self._on_rotate(None,row)

    def rotate_if_needed(self):
        self._ensure_authenticated()
        if self._current.used>145:self._rotate('iteration_headroom',None,None)

    def _rotate(self,reason,method,scope):
        old=self._current
        row=dict(reason=reason,method=method,scope=scope,previous_used=old.used,
                 local_session_rotation=True,provider_retry=False,
                 authentication_attempt=1,authenticated=False)
        try:
            new=self._factory()
            for name in ('limit','per_scope'):
                if hasattr(old,name) and getattr(new,name,None)!=getattr(old,name):
                    raise BoundaryError('position_session_configuration_drift')
            self._current=new
            self._authenticated=False
            self._authentication_attempt=1
            new.verify_chain()
            self._authenticated=True
            row['authenticated']=True
        except BoundaryError as exc:
            row['boundary']=str(exc)
            raise
        finally:
            self._on_rotate(old.telemetry(),row)

    def _invoke(self,operation,args,kwargs):
        self._ensure_authenticated()
        if operation=='verify_chain':self._authenticated=False
        try:
            value=getattr(self._current,operation)(*args,**kwargs)
            if operation=='verify_chain':self._authenticated=True
            return value
        except BoundaryError as exc:
            if str(exc)!='provider_session_budget_exhausted':raise
        # Budget checks precede transport. Retry only the rejected operation once
        # on a newly authenticated session, not the monitor/qualification/entry.
        method=args[0] if operation=='call' and args else operation
        self._rotate('local_session_budget',method,kwargs.get('scope'))
        if operation=='verify_chain':return None
        return getattr(self._current,operation)(*args,**kwargs)

    def call(self,*args,**kwargs):return self._invoke('call',args,kwargs)
    def batch(self,*args,**kwargs):return self._invoke('batch',args,kwargs)
    def verify_chain(self,*args,**kwargs):return self._invoke('verify_chain',args,kwargs)
