"""Finite operational provider exposure, shared by the existing child processes.

Reuses the previously validated physical/native transport boundaries and frozen
read-only method prices. It does not run the technical proof, inject a restart,
alter strategy work or assert measured billing. No network occurs on import.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from engineering.solana_capacity.proof_limits import (
    CeilingReached,MAX_FRAME,PUBLISHED,STREAM_HOST,endpoint_family)

LIMITS=dict(rpc_cu=720000,rpc_elements=10000,http_attempts=10000,
            native_bytes=4*1024**3,native_stop_bytes=2*1024**3-MAX_FRAME,
            native_inflight_bytes=2*1024**3)


class Budget:
    def __init__(self,path):
        self.path=Path(path)
        with closing(self.db()) as db:
            self.started=float(db.execute("SELECT value FROM run WHERE key='started'").fetchone()[0])
        self.clock=time.monotonic;self.ready_at=None
        self.time={'total_wall_seconds':1800}
        self.limits=LIMITS

    def db(self):
        return sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5,isolation_level=None)

    @classmethod
    def create(cls,path):
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        # Existing consumption must never become a fresh allowance on restart.
        descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(descriptor)
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE run(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('CREATE TABLE streams(id TEXT PRIMARY KEY,remaining INTEGER NOT NULL,closed INTEGER NOT NULL)')
            db.executemany('INSERT INTO run VALUES(?,?)',[
                ('started',str(time.monotonic())),('boot',Path('/proc/sys/kernel/random/boot_id').read_text().strip()),
                ('reason',''),('rpc_cu','0'),('rpc_elements','0'),('http_attempts','0'),
                ('native_bytes','0'),('native_reserved','0'),('native_uncertain_bytes','0')])
            db.commit()
        return cls(path)

    def snapshot(self):
        with closing(self.db()) as db:return dict(db.execute('SELECT key,value FROM run'))

    def change(self,add=None,*,reason=None,check=True):
        with closing(self.db()) as db:
            db.execute('BEGIN IMMEDIATE');state=dict(db.execute('SELECT key,value FROM run'))
            failure=state['reason']
            if check:
                if state['boot']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip():failure='bounded_run_host_restarted'
                elif time.monotonic()-float(state['started'])>=1800:failure='bounded_run_wall_limit'
            for key,n in (add or {}).items():state[key]=str(int(state[key])+n)
            if add:
                for key in ('rpc_cu','rpc_elements','http_attempts'):
                    if int(state[key])>LIMITS[key]:failure=key+'_limit'
                if int(state['native_reserved'])>LIMITS['native_inflight_bytes']:failure='native_inflight_limit'
                if int(state['native_bytes'])+int(state['native_uncertain_bytes'])>=LIMITS['native_stop_bytes']:
                    failure='native_payload_stop'
            failure=failure or reason or ''
            if failure and add and check:
                # RPC/stream reservations which would exceed a ceiling do not
                # dispatch. Delivery/closure accounting uses check=False.
                state=dict(db.execute('SELECT key,value FROM run'))
            state['reason']=failure
            db.executemany('UPDATE run SET value=? WHERE key=?',[(v,k) for k,v in state.items()]);db.execute('COMMIT')
        if failure and check:raise CeilingReached(failure)
        return state

    def admission(self):self.change()
    def fail(self,reason):
        self.change(reason=reason,check=False)
        raise CeilingReached(reason)

    def reserve_http(self,endpoint,calls):
        try:family=endpoint_family(endpoint)
        except ValueError:self.fail('bounded_provider_endpoint')
        if not isinstance(calls,list) or not 1<=len(calls)<=200:self.fail('bounded_rpc_shape')
        methods=[c.get('method') if isinstance(c,dict) else None for c in calls]
        if any(m not in PUBLISHED[family] for m in methods):self.fail('bounded_unpriced_or_writing_method')
        self.change(dict(rpc_cu=sum(PUBLISHED[family][m] for m in methods),
                         rpc_elements=len(methods),http_attempts=1))

    def stream_open(self,transport):
        return self.native_event('open',transport=transport)

    def stream_close(self,reserve,*,transport=None,unread_possible=False):
        self.native_event('close',token=reserve,uncertain=unread_possible)

    def native(self,transport,size,*,token):
        self.native_event('frame',token=token,size=size)

    def native_event(self,kind,*,transport=None,token=None,size=0,uncertain=False):
        """Once stopping, delivered tail consumes its pre-reserved SDK bytes."""
        if kind=='frame' and (type(size) is not int or not 0<=size<=MAX_FRAME):self.fail('native_frame_bound')
        with closing(self.db()) as db:
            db.execute('BEGIN IMMEDIATE');state=dict(db.execute('SELECT key,value FROM run'))
            failure=state['reason'];row=None
            if state['boot']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip():
                failure=failure or 'bounded_run_host_restarted'
            elif time.monotonic()-float(state['started'])>=1800:
                failure=failure or 'bounded_run_wall_limit'
            if kind=='open':
                if transport not in ('yellowstone','solana_websocket'):failure=failure or 'native_transport_bound'
                if time.monotonic()-float(state['started'])>=1800:failure=failure or 'bounded_run_wall_limit'
                reserve=MAX_FRAME*(3 if transport=='solana_websocket' else 2)
                total=sum(int(state[k]) for k in ('native_bytes','native_uncertain_bytes','native_reserved'))
                if (int(state['native_reserved'])+reserve>LIMITS['native_inflight_bytes']
                        or total+reserve>LIMITS['native_bytes']):failure=failure or 'native_inflight_limit'
                if int(state['http_attempts'])>=LIMITS['http_attempts']:failure=failure or 'http_attempts_limit'
                if not failure:
                    token=uuid.uuid4().hex;db.execute('INSERT INTO streams VALUES(?,?,0)',(token,reserve))
                    state['native_reserved']=str(int(state['native_reserved'])+reserve)
                    state['http_attempts']=str(int(state['http_attempts'])+1)
            else:
                row=db.execute('SELECT remaining,closed FROM streams WHERE id=?',(token,)).fetchone()
                if not row:failure=failure or 'native_reservation_missing'
                elif kind=='frame':
                    if row[1]:failure=failure or 'native_frame_after_close'
                    elif failure:
                        if size>row[0]:failure='native_shutdown_buffer_exceeded'
                        else:
                            db.execute('UPDATE streams SET remaining=remaining-? WHERE id=?',(size,token))
                            state['native_reserved']=str(int(state['native_reserved'])-size)
                    state['native_bytes']=str(int(state['native_bytes'])+size)
                elif kind=='close' and not row[1]:
                    db.execute('UPDATE streams SET remaining=0,closed=1 WHERE id=?',(token,))
                    state['native_reserved']=str(int(state['native_reserved'])-row[0])
                    if uncertain:state['native_uncertain_bytes']=str(int(state['native_uncertain_bytes'])+row[0])
            if int(state['native_bytes'])+int(state['native_uncertain_bytes'])>=LIMITS['native_stop_bytes']:
                failure=failure or 'native_payload_stop'
            state['reason']=failure
            db.executemany('UPDATE run SET value=? WHERE key=?',[(v,k) for k,v in state.items()]);db.execute('COMMIT')
        if failure and kind!='close':raise CeilingReached(failure)
        return token


def install():
    path=os.environ.get('MM_BOUNDED_PROVIDER_DB')
    if not path:return
    budget=Budget(path)
    import urllib.request
    from urllib.parse import urlsplit
    from urllib.request import HTTPRedirectHandler,ProxyHandler,build_opener
    from meme_machine.lanes.pons import provider
    from meme_machine import solana_selective_source as source
    import grpc
    from engineering.solana_capacity.proof_transport import Channel,Stream,WebSocketContext
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):budget.fail('bounded_http_redirect')
    opener=build_opener(ProxyHandler({}),NoRedirect()).open
    def opened(request,*args,**kwargs):
        try:body=json.loads(request.data)
        except (ValueError,TypeError,AttributeError):budget.fail('bounded_non_rpc_http')
        budget.reserve_http(request.full_url,body if isinstance(body,list) else [body])
        budget.admission()
        return opener(request,timeout=min(8,float(kwargs.get('timeout',8))))
    urllib.request.urlopen=opened;provider.urlopen=opened
    # The audited native wrappers are reused without proof scheduling hooks or
    # its forced disconnect: ready_at remains None for the operational run.
    class Native:
        def __init__(self):
            self.budget=budget;self.disconnect=False;self.disconnect_receipt=None
            self.ws_opening=0
    class StreamBudget:
        def __init__(self):self.token=None
        def __getattr__(self,name):return getattr(budget,name)
        def stream_open(self,transport):
            self.token=budget.stream_open(transport);return self.token
        def native(self,transport,size):return budget.native(transport,size,token=self.token)
    class MeteredChannel(Channel):
        def stream_stream(self,path,**kwargs):
            if path!='/geyser.Geyser/Subscribe':budget.fail('bounded_native_method')
            context=Native();context.budget=StreamBudget()
            original=kwargs.get('response_deserializer',lambda raw:raw)
            def decoded(raw):context.budget.native('yellowstone',len(raw));return original(raw)
            kwargs['response_deserializer']=decoded;factory=self.raw.stream_stream(path,**kwargs)
            def call(*args,**options):
                token=context.budget.stream_open('yellowstone')
                try:return Stream(factory(*args,**options),context,token)
                except BaseException:budget.stream_close(token);raise
            return call
    channel=grpc.aio.secure_channel;websocket=source.connect
    def bounded_channel(target,*args,**kwargs):
        if target!=STREAM_HOST:budget.fail('bounded_native_endpoint')
        budget.admission();options=dict(kwargs.get('options',()))
        options.update({'grpc.max_receive_message_length':MAX_FRAME,'grpc.enable_retries':0,
                        'grpc.http2.bdp_probe':0,'grpc.http2.initial_stream_window_size':MAX_FRAME,
                        'grpc.http2.initial_connection_window_size':MAX_FRAME})
        kwargs['options']=tuple(options.items())
        return MeteredChannel(channel(target,*args,**kwargs),Native())
    def bounded_websocket(url,*args,**kwargs):
        p=urlsplit(url)
        if p.scheme!='wss' or p.hostname!=STREAM_HOST.split(':')[0]:budget.fail('bounded_websocket_endpoint')
        endpoint_family('https://solana-mainnet.g.alchemy.com'+p.path)
        kwargs.update(max_size=MAX_FRAME,max_queue=2,compression=None,open_timeout=8,close_timeout=1)
        context=Native();context.budget=StreamBudget()
        return WebSocketContext(websocket(url,*args,**kwargs),context)
    grpc.aio.secure_channel=bounded_channel;source.connect=bounded_websocket
