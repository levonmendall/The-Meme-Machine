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
from decimal import Decimal

from engineering.solana_capacity.proof_limits import (
    CeilingReached,MAX_FRAME,PUBLISHED,STREAM_HOST,endpoint_family)

LIMITS=dict(rpc_cu=720000,rpc_elements=10000,http_attempts=10000,
            native_bytes=4*1024**3,native_stop_bytes=2*1024**3-MAX_FRAME,
            native_inflight_bytes=2*1024**3)

def modeled_spend(state):
    # Conservative application-byte model, not an invoice assertion. Charge
    # every HTTP method at the frozen CU price, even non-Alchemy endpoints, and
    # all native transports at the higher published byte rate. Reserve unread
    # SDK buffers too. Account plan fees/provider wire metering remain unknown.
    native=sum(int(state[k]) for k in ('native_bytes','native_uncertain_bytes','native_reserved'))
    return Decimal(state['rpc_cu'])*Decimal('0.525')/1000000+Decimal(native)*Decimal('0.0002')*Decimal('0.525')/1000000


class Budget:
    def __init__(self,path,*,phase='bootstrap'):
        if phase not in ('bootstrap','continuation','recovery'):raise ValueError('provider_usage_phase')
        self.phase=phase;self.prefix='' if phase=='bootstrap' else phase+'.'
        self.path=Path(path)
        with closing(self.db()) as db:
            state=self.read(db)
        self.started=float(state['started'])
        self.started_wall=float(state.get('started_wall',time.time()))
        self.seconds=int(state.get('wall_seconds',1800))
        if phase!='bootstrap':self.started=time.monotonic()-max(0,time.time()-self.started_wall)
        self.clock=time.monotonic;self.ready_at=None
        self.time={'total_wall_seconds':self.seconds}
        self.limits=json.loads(state['limits']) if 'limits' in state else LIMITS

    def read(self,db):
        return {key[len(self.prefix):]:value for key,value in db.execute('SELECT key,value FROM run')
            if (key.startswith(self.prefix) if self.prefix else '.' not in key)}

    def write(self,db,state):
        db.executemany('UPDATE run SET value=? WHERE key=?',[(str(v),self.prefix+k) for k,v in state.items()])

    def expired(self,state):
        if self.phase=='bootstrap':return time.monotonic()-float(state['started'])>=self.seconds
        return time.time()>=float(state['started_wall'])+self.seconds

    @staticmethod
    def add_continuation(db,envelope):
        db.execute('INSERT INTO run VALUES(?,?)',('continuation_envelope',json.dumps(envelope,sort_keys=True)))
        for phase in ('continuation','recovery'):
            values=dict(started=str(time.monotonic()),started_wall=str(int(time.time())),
                boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                wall_seconds=str(envelope['maximum_seconds']),limits=json.dumps(envelope[phase]),
                reason='',rpc_cu='0',rpc_elements='0',http_attempts='0',native_bytes='0',
                native_reserved='0',native_uncertain_bytes='0',http_bytes='0',alchemy_rpc_cu='0',
                solana_rpc_elements='0',robinhood_rpc_elements='0',native_opens='0',
                modeled_spend_limit=envelope[phase+'_modeled_spend_usd'],
                reconnect_limit=str(envelope['maximum_reconnects']))
            db.executemany('INSERT INTO run VALUES(?,?)',[(phase+'.'+k,v) for k,v in values.items()])

    def db(self):
        return sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5,isolation_level=None)

    @classmethod
    def create(cls,path,*,continuation=None):
        if continuation is not None:
            from .position_continuation import validate_envelope
            validate_envelope(continuation)
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        # Existing consumption must never become a fresh allowance on restart.
        descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(descriptor)
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE run(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('CREATE TABLE streams(id TEXT PRIMARY KEY,remaining INTEGER NOT NULL,closed INTEGER NOT NULL)')
            db.executemany('INSERT INTO run VALUES(?,?)',[
                ('started',str(time.monotonic())),('boot',Path('/proc/sys/kernel/random/boot_id').read_text().strip()),
                ('started_wall',str(int(time.time()))),('wall_seconds','1800'),('phase','BOOTSTRAP'),('work_mode','DISCOVERY'),
                ('reason',''),('rpc_cu','0'),('rpc_elements','0'),('http_attempts','0'),
                ('native_bytes','0'),('native_reserved','0'),('native_uncertain_bytes','0'),
                ('http_bytes','0'),('alchemy_rpc_cu','0'),('solana_rpc_elements','0'),('robinhood_rpc_elements','0'),
                ('native_opens','0'),('modeled_spend_limit','3')])
            if continuation is not None:cls.add_continuation(db,continuation)
            db.commit()
        return cls(path)

    def snapshot(self):
        with closing(self.db()) as db:return self.read(db)

    def change(self,add=None,*,reason=None,check=True):
        with closing(self.db()) as db:
            db.execute('BEGIN IMMEDIATE');state=self.read(db)
            failure=state['reason']
            if check:
                if self.phase=='bootstrap' and state['boot']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip():failure='bounded_run_host_restarted'
                elif self.expired(state):failure='bounded_run_wall_limit'
            for key,n in (add or {}).items():state[key]=str(int(state[key])+n)
            if add:
                for key in ('rpc_cu','rpc_elements','http_attempts'):
                    if int(state[key])>self.limits[key]:failure=key+'_limit'
                if 'http_bytes' in self.limits and int(state['http_bytes'])>self.limits['http_bytes']:
                    failure='http_bytes_limit'
                if int(state['native_reserved'])>self.limits['native_inflight_bytes']:failure='native_inflight_limit'
                if int(state['native_bytes'])+int(state['native_uncertain_bytes'])>=self.limits['native_stop_bytes']:
                    failure='native_payload_stop'
                if modeled_spend(state)>Decimal(state['modeled_spend_limit']):failure='modeled_spend_limit'
            failure=failure or reason or ''
            if failure and add and check:
                # RPC/stream reservations which would exceed a ceiling do not
                # dispatch. Delivery/closure accounting uses check=False.
                state=self.read(db)
            state['reason']=failure
            self.write(db,state);db.execute('COMMIT')
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
        cu=sum(PUBLISHED[family][m] for m in methods)
        from urllib.parse import urlsplit
        alchemy=urlsplit(endpoint).hostname.endswith('.alchemy.com')
        self.change(dict(rpc_cu=cu,alchemy_rpc_cu=cu if alchemy else 0,
            rpc_elements=len(methods),http_attempts=1,**{family+'_rpc_elements':len(methods)}))
        return self

    def http_delivery(self,size):
        # Delivered data is never rolled back, including an exhausted response.
        self.change(dict(http_bytes=size),check=False)
        if 'http_bytes' in self.limits and int(self.snapshot()['http_bytes'])>self.limits['http_bytes']:
            self.fail('http_bytes_limit')

    def stream_open(self,transport):
        return self.native_event('open',transport=transport)

    def stream_close(self,reserve,*,transport=None,unread_possible=False):
        self.native_event('close',token=reserve,uncertain=unread_possible)

    def native(self,transport,size,*,token):
        self.native_event('frame',token=token,size=size)

    def native_event(self,kind,*,transport=None,token=None,size=0,uncertain=False,physical=True):
        """Once stopping, delivered tail consumes its pre-reserved SDK bytes."""
        if kind=='frame' and (type(size) is not int or not 0<=size<=MAX_FRAME):self.fail('native_frame_bound')
        with closing(self.db()) as db:
            db.execute('BEGIN IMMEDIATE');state=self.read(db)
            failure=state['reason'];row=None
            if self.phase=='bootstrap' and state['boot']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip():
                failure=failure or 'bounded_run_host_restarted'
            elif self.expired(state):
                failure=failure or 'bounded_run_wall_limit'
            if kind=='open':
                if transport not in ('yellowstone','solana_websocket'):failure=failure or 'native_transport_bound'
                if self.expired(state):failure=failure or 'bounded_run_wall_limit'
                reserve=MAX_FRAME*(3 if transport=='solana_websocket' else 2)
                total=sum(int(state[k]) for k in ('native_bytes','native_uncertain_bytes','native_reserved'))
                if (int(state['native_reserved'])+reserve>self.limits['native_inflight_bytes']
                        or total+reserve>self.limits['native_bytes']):failure=failure or 'native_inflight_limit'
                if physical and int(state['http_attempts'])>=self.limits['http_attempts']:failure=failure or 'http_attempts_limit'
                if physical and int(state['native_opens'])>=int(state.get('reconnect_limit','10000')):
                    failure=failure or 'native_reconnect_limit'
                if modeled_spend(dict(state,native_reserved=str(int(state['native_reserved'])+reserve)))>Decimal(state['modeled_spend_limit']):
                    failure=failure or 'modeled_spend_limit'
                if not failure:
                    token=self.prefix+uuid.uuid4().hex;db.execute('INSERT INTO streams VALUES(?,?,0)',(token,reserve))
                    from meme_machine.shared_capital.runtime import process_identity
                    db.execute('INSERT INTO run VALUES(?,?)',('stream_owner.'+token,
                        json.dumps(dict(pid=os.getpid(),start=process_identity(os.getpid())))))
                    state['native_reserved']=str(int(state['native_reserved'])+reserve)
                    state['http_attempts']=str(int(state['http_attempts'])+int(physical))
                    state['native_opens']=str(int(state['native_opens'])+int(physical))
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
            if int(state['native_bytes'])+int(state['native_uncertain_bytes'])>=self.limits['native_stop_bytes']:
                failure=failure or 'native_payload_stop'
            if modeled_spend(state)>Decimal(state['modeled_spend_limit']):failure=failure or 'modeled_spend_limit'
            state['reason']=failure
            self.write(db,state);db.execute('COMMIT')
        if failure and kind!='close':raise CeilingReached(failure)
        return token


class PhaseBudget:
    """One existing usage database; immutable, separately counted allowances."""
    def __init__(self,path):
        self.path=Path(path);self.bootstrap=Budget(path)
        self.envelope=json.loads(self.bootstrap.snapshot()['continuation_envelope'])
        self.started=self.bootstrap.started;self.clock=time.monotonic;self.ready_at=None
        self.time=dict(total_wall_seconds=self.envelope['maximum_seconds'])
        self.limits=self.envelope['continuation']
        from .exceptional_window import adopt
        adopt(self)

    def phase(self):return self.bootstrap.snapshot()['phase']
    def fault(self):return json.loads(self.bootstrap.snapshot().get('fault','{}'))

    def set_phase(self,phase,reason):
        from .position_continuation import PHASES
        if phase not in PHASES:raise ValueError('position_continuation_phase')
        with closing(self.bootstrap.db()) as db:
            db.execute('BEGIN IMMEDIATE');state=self.bootstrap.read(db)
            ranks={name:n for n,name in enumerate(PHASES)}
            if ranks[phase]<ranks[state['phase']]:db.execute('ROLLBACK');return
            db.execute('UPDATE run SET value=? WHERE key=?',(phase,'phase'))
            if phase!='BOOTSTRAP':db.execute("UPDATE run SET value='POSITION_ONLY' WHERE key='work_mode'")
            if phase=='RECOVERY' and 'recovery_activated_wall' not in state:
                now=time.time();remaining=max(0,float(state['started_wall'])+self.envelope['maximum_seconds']-now)
                db.executemany('UPDATE run SET value=? WHERE key=?',[
                    (str(now),'recovery.started_wall'),
                    (str(int(min(remaining,self.envelope['recovery_seconds']))),'recovery.wall_seconds')])
                db.execute('INSERT INTO run VALUES(?,?)',('recovery_activated_wall',str(now)))
            if phase in ('RECOVERY','FAULT'):
                value=json.dumps(dict(phase=phase,reason=reason,at=int(time.time()),
                    funding_closed=True,protected=False,action='restore_provider_or_review_remaining_resource_allowance'))
                db.execute('INSERT INTO run VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('fault',value))
            db.execute('COMMIT')

    def position_work_only(self):
        with closing(self.bootstrap.db()) as db:db.execute("UPDATE run SET value='POSITION_ONLY' WHERE key='work_mode'")

    def reap_orphans(self):
        """Crash-lost SDK buffers remain charged once; live peer owners survive."""
        from meme_machine.shared_capital.runtime import process_identity
        with closing(self.bootstrap.db()) as db:
            rows=list(db.execute("SELECT s.id,r.value FROM streams s JOIN run r ON r.key='stream_owner.'||s.id WHERE s.closed=0"))
        for token,raw in rows:
            owner=json.loads(raw)
            try:
                alive=(process_identity(owner['pid'])==owner['start'] and
                    Path('/proc/'+str(owner['pid'])+'/stat').read_text().rpartition(')')[2].split()[0]!='Z')
            except OSError:alive=False
            if not alive:
                phase=token.split('.')[0] if '.' in token else 'bootstrap'
                Budget(self.path,phase=phase).stream_close(token,unread_possible=True)

    def selected(self):
        phase=self.phase()
        if phase=='BOOTSTRAP' and (self.bootstrap.snapshot()['reason'] or
                time.time()>=self.bootstrap.started_wall+1735):
            self.bootstrap.change(reason='bootstrap_management_handoff',check=False)
            self.set_phase('CONTINUATION','bootstrap_management_handoff');phase=self.phase()
        if phase in ('FAULT','FLAT'):raise CeilingReached('position_continuation_'+phase.lower())
        return Budget(self.path,phase=phase.lower())

    def invoke(self,method,*args,**kwargs):
        budget=self.selected()
        try:return getattr(budget,method)(*args,**kwargs)
        except CeilingReached as error:
            recoverable=error.reason.startswith(('rpc_','http_','native_payload','native_inflight','bounded_run_','modeled_spend_','native_reconnect_'))
            if not recoverable or budget.phase=='recovery':
                self.set_phase('FAULT',error.reason);raise
            if budget.phase=='bootstrap':
                self.set_phase('CONTINUATION',error.reason)
            else:self.set_phase('RECOVERY',error.reason)
            return self.invoke(method,*args,**kwargs)

    def snapshot(self):
        try:return self.selected().snapshot()
        except CeilingReached:return dict(reason=self.phase(),fault=self.fault())

    def admission(self):return self.invoke('admission')
    def reserve_http(self,endpoint,calls):return self.invoke('reserve_http',endpoint,calls)
    def http_delivery(self,size):
        # Responses belong to the phase which reserved them. Never charge an
        # already delivered exhausted response a second time in the next phase.
        budget=self.selected()
        try:budget.http_delivery(size)
        except CeilingReached as error:
            self.advance(budget,error.reason)

    def advance(self,budget,reason):
        phase={'bootstrap':'CONTINUATION','continuation':'RECOVERY','recovery':'FAULT'}[budget.phase]
        self.set_phase(phase,reason)
        if phase=='FAULT':raise CeilingReached(reason)

    def usage(self):
        phases={phase:Budget(self.path,phase=phase).snapshot() for phase in ('bootstrap','continuation','recovery')}
        for row in phases.values():row['modeled_spend_usd']=str(modeled_spend(row))
        root=self.bootstrap.snapshot()
        return dict(phase=root['phase'],fault=self.fault(),
            provider_fault=json.loads(root.get('provider_fault','{}')),phases=phases)

    def stream_open(self,transport):
        self.admission();budget=self.selected()
        try:token=budget.stream_open(transport)
        except CeilingReached as error:
            if error.reason not in ('native_inflight_limit','http_attempts_limit','native_reconnect_limit','modeled_spend_limit','bounded_run_wall_limit'):
                self.fail(error.reason)
            self.advance(budget,error.reason);return self.stream_open(transport)
        return dict(phase=budget.phase,token=token,transport=transport)

    def native(self,transport,size,*,token):
        budget=self.selected()
        if token['phase']!=budget.phase:
            old=Budget(self.path,phase=token['phase'])
            old.stream_close(token['token'],unread_possible=True)
            # Same live connection; reserve its SDK buffers in the next phase,
            # without inventing another physical connection attempt.
            try:next_token=budget.native_event('open',transport=transport,physical=False)
            except CeilingReached as error:
                self.advance(budget,error.reason)
                # The old reservation was already closed idempotently.
                return self.native(transport,size,token=token)
            token.update(phase=budget.phase,token=next_token)
        try:budget.native(transport,size,token=token['token'])
        except CeilingReached as error:
            if error.reason not in ('native_payload_stop','bounded_run_wall_limit','modeled_spend_limit'):
                self.set_phase('FAULT',error.reason);raise
            # This delivered frame was already counted in its original phase.
            # The next frame transfers the same stream's reservation.
            self.advance(budget,error.reason)

    def stream_close(self,token,*,transport=None,unread_possible=False):
        Budget(self.path,phase=token['phase']).stream_close(token['token'],unread_possible=unread_possible)

    def fail(self,reason):
        self.set_phase('FAULT',reason);raise CeilingReached(reason)


class DeliveredResponse:
    def __init__(self,raw,budget,router=None):self.raw=raw;self.budget=budget;self.router=router
    def __getattr__(self,name):return getattr(self.raw,name)
    def __enter__(self):self.raw.__enter__();return self
    def __exit__(self,*args):return self.raw.__exit__(*args)
    def read(self,*args,**kwargs):
        data=self.raw.read(*args,**kwargs)
        try:self.budget.http_delivery(len(data))
        except CeilingReached as error:
            if self.router is None:raise
            self.router.advance(self.budget,error.reason)
        return data


def install():
    path=os.environ.get('MM_BOUNDED_PROVIDER_DB')
    if not path:return
    budget=Budget(path)
    if 'continuation_envelope' in budget.snapshot():budget=PhaseBudget(path)
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
        charged=budget.reserve_http(request.full_url,body if isinstance(body,list) else [body])
        budget.admission()
        return DeliveredResponse(opener(request,timeout=min(8,float(kwargs.get('timeout',8)))),charged,
            budget if isinstance(budget,PhaseBudget) else None)
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
