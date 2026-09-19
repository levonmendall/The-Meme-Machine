"""Bounded paper experiment; one writer loop, read-only status publication."""
import argparse
import json
import os
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .engine import Engine
from .market_native_runtime import MarketNativeRuntime
from .postgrad import PostGraduationAdapter
from .provider import PumpAdapter, Unavailable
from .solana_read_rpc import new_rpc, primary_rpc_url
from .pumpswap_runtime import POSTGRAD_WAIT_SECONDS, PumpSwapPaperRuntime
from .store import Store
from .stream import PumpLogStream, PumpTape, WINDOW_SECONDS


def tick(engine, adapter, now):
    """Legacy HTTP-history tick retained for captured regression compatibility."""
    s=engine.store.state
    for mint,p in list(s['positions'].items()):
        if now>=p['next_monitor']:
            source_error=None
            try:
                snap=adapter.snapshot(mint,now,priority=True)
            except (Unavailable,ValueError) as exc:
                snap={}
                source_error=exc
            engine.monitor(mint,snap,int(time.time()),source_error=source_error)
    for oid,o in list(s['orders'].items()):
        if o['status']=='reserved' and now>=o['due']:
            try:
                snap=adapter.snapshot(o['mint'],now,priority=True)
            except (Unavailable,ValueError):
                snap={}
            engine.fill(oid,snap,int(time.time()))
    if engine.store.pressure():
        return
    for wallet in sorted(engine.seeds):
        try:
            events,covered=adapter.history(wallet,now)
            nominations=engine.scout(events,int(time.time()))
            with engine.store.transaction('discovery_coverage'):
                observed=int(time.time())
                s.setdefault('coverage',{})[wallet]=dict(window_covered=covered,observed_events=len(events),time=observed)
                if not covered:
                    engine.quarantine('wallet_window_incomplete',observed)
                if not nominations:
                    engine.note('healthy_scout_no_nomination' if covered else 'incomplete_scout_window',None,observed)
            for nomination in nominations[:2]:
                snap=adapter.snapshot(nomination['mint'],now)
                market,covered=adapter.history(snap['pool'],now,require_coverage=True)
                concentration=adapter.concentration(nomination['mint'],snap)
                snap=adapter.snapshot(nomination['mint'],int(time.time()))
                engine.consider(nomination,dict(snapshot=snap,events=market,covered=covered,
                                                concentration_bps=concentration),int(time.time()))
        except (Unavailable,ValueError):
            with engine.store.transaction('provider_gap'):
                observed=int(time.time())
                engine.quarantine('discovery_data_unavailable',observed)
                engine.note('provider_or_evidence_failure',None,observed)
    with engine.store.transaction('heartbeat'):
        s['provider']=dict(requests=adapter.rpc.calls,failures=adapter.rpc.failures,
                           cache_hits=adapter.rpc.cache_hits,limit=adapter.rpc.limit,
                           infrastructure_spend_usd=0,provider_spend_usd=0 if getattr(adapter.rpc,'failover_count',0)==0 else None)


def _monitor_existing(engine, adapter, now, pumpswap_runtime=None):
    """Positions/orders outrank discovery and survive a Pump -> PumpSwap graduation."""
    s=engine.store.state
    for mint,p in list(s['positions'].items()):
        if now<p['next_monitor']:
            continue
        if pumpswap_runtime is not None and (
                p.get('surface') in ('pumpswap','graduating-pumpswap') or
                p.get('postgrad_handoff')):
            pumpswap_runtime.monitor_existing_position(mint)
            continue
        try:
            snap=adapter.snapshot(mint,now,priority=True)
        except (Unavailable,ValueError) as exc:
            if pumpswap_runtime is not None:
                result=pumpswap_runtime.monitor_existing_position(mint)
                if result != 'not_graduated':
                    continue
            engine.monitor(mint,{},int(time.time()),source_error=exc)
            continue
        if pumpswap_runtime is not None:
            try:
                handoff=pumpswap_runtime.handoff_from_snapshot(snap)
            except (ValueError,KeyError,TypeError):
                handoff=None
            if handoff is not None:
                pumpswap_runtime.monitor_existing_position(mint,graduation_snapshot=snap)
                continue
        engine.monitor(mint,snap,int(time.time()))

    for oid,o in list(s['orders'].items()):
        if o['status']!='reserved' or now<o['due']:
            continue
        if pumpswap_runtime is not None and (
                o.get('surface')=='pumpswap' or o.get('postgrad_handoff')):
            pumpswap_runtime.fill_existing_order(oid)
            continue
        try:
            snap=adapter.snapshot(o['mint'],now,priority=True)
        except (Unavailable,ValueError):
            if pumpswap_runtime is not None:
                result=pumpswap_runtime.fill_existing_order(oid)
                if result != 'not_graduated':
                    continue
                if int(time.time())-int(o['created']) <= POSTGRAD_WAIT_SECONDS:
                    continue
            engine.fill(oid,{},int(time.time()))
            continue
        if pumpswap_runtime is not None:
            try:
                handoff=pumpswap_runtime.handoff_from_snapshot(snap)
            except (ValueError,KeyError,TypeError):
                handoff=None
            if handoff is not None:
                pumpswap_runtime.fill_existing_order(oid,graduation_snapshot=snap)
                continue
        engine.fill(oid,snap,int(time.time()))


def tick_stream(engine, adapter, tape, now, cursor, pumpswap_runtime=None):
    """Legacy scout-backed stream tick retained only for regression compatibility.

    The prospective CLI no longer calls this function. Active prospective discovery is
    market-native through MarketNativeRuntime; keeping this helper allows historical
    scout/captured tests to prove old lifecycle behavior without keeping scouts active.
    """
    _monitor_existing(engine,adapter,now,pumpswap_runtime=pumpswap_runtime)
    s=engine.store.state
    status=tape.status(now)
    if engine.store.pressure():
        return cursor

    if not status['covered']:
        with engine.store.transaction('stream_coverage'):
            if status['connected'] and status['warm_seconds'] < WINDOW_SECONDS:
                until=now+(WINDOW_SECONDS-status['warm_seconds'])
                s['entry_quarantine_until']=max(s.get('entry_quarantine_until',0),until)
            else:
                engine.quarantine('stream_continuity_unavailable',now)
            s.setdefault('coverage',{})['pump_program_stream']=dict(
                window_covered=False,time=now,stream=status)
        return None

    if cursor is None:
        cursor=tape.latest_sequence()
        with engine.store.transaction('stream_coverage_ready'):
            s.setdefault('coverage',{})['pump_program_stream']=dict(
                window_covered=True,time=now,stream=status)
        return cursor

    fresh,cursor=tape.events_since(cursor)
    seed_events=[e for e in fresh if e['wallet'] in engine.seeds]
    nominations=engine.scout(seed_events,now) if seed_events else []
    with engine.store.transaction('stream_coverage'):
        s.setdefault('coverage',{})['pump_program_stream']=dict(
            window_covered=True,time=now,stream=status,
            fresh_trade_events=len(fresh),fresh_seed_events=len(seed_events))
        if not nominations and seed_events:
            engine.note('healthy_scout_no_nomination',None,now)

    for nomination in nominations[:2]:
        try:
            initial=adapter.snapshot(nomination['mint'],now)
            observed=int(time.time())
            if not tape.covered(observed):
                with engine.store.transaction('stream_gap_before_qualification'):
                    engine.quarantine('stream_continuity_unavailable',observed)
                break
            market=tape.window(nomination['mint'],observed,max_slot=initial['slot'])
            concentration=adapter.concentration(nomination['mint'],initial)
            final=adapter.snapshot(nomination['mint'],int(time.time()))
            qualified_at=int(time.time())
            if not tape.covered(qualified_at):
                with engine.store.transaction('stream_gap_before_qualification'):
                    engine.quarantine('stream_continuity_unavailable',qualified_at)
                break
            market=tape.window(nomination['mint'],qualified_at,max_slot=final['slot'])
            engine.consider(nomination,dict(snapshot=final,events=market,covered=True,
                                            concentration_bps=concentration),qualified_at)
        except (Unavailable,ValueError,KeyError,TypeError):
            with engine.store.transaction('provider_gap'):
                observed=int(time.time())
                engine.quarantine('discovery_data_unavailable',observed)
                engine.note('provider_or_evidence_failure',nomination.get('mint'),observed)

    with engine.store.transaction('heartbeat'):
        s['provider']=dict(requests=adapter.rpc.calls,http_requests=adapter.rpc.http_requests,
                           failures=adapter.rpc.failures,cache_hits=adapter.rpc.cache_hits,
                           limit=adapter.rpc.limit,stream=tape.status(int(time.time())),
                           infrastructure_spend_usd=0,
                           provider_spend_usd=0 if getattr(adapter.rpc,'url',None)=='https://api.mainnet-beta.solana.com' else None)
    return cursor


def replay(engine,path):
    with open(path) as stream:
        for line in stream:
            if len(line)>2_000_000:
                raise ValueError('frame_size_limit')
            frame=json.loads(line)
            now=frame['now']
            for mint in list(engine.store.state['positions']):
                engine.monitor(mint,frame.get('snapshots',{}).get(mint,{}),now)
            for oid,o in list(engine.store.state['orders'].items()):
                if o['status']=='reserved':
                    engine.fill(oid,frame.get('snapshots',{}).get(o['mint'],{}),now)
            for nomination in engine.scout(frame.get('events',[]),now):
                if nomination['mint'] in frame.get('evidence',{}):
                    engine.consider(nomination,frame['evidence'][nomination['mint']],now)
    return engine.status(now)


def _retire_scout_state(store):
    """One-time prospective migration; never touches economic/order/position state."""
    s=store.state
    if 'retired_scout_config' in s:
        return False
    with store.transaction('retire_scout_discovery'):
        s['retired_scout_config']=s.pop('scout_config',None)
        funnel=s.setdefault('funnel',{})
        scout_keys=('scout_batches','observed_events','seed_events','nominations')
        s['retired_scout_funnel']={key:int(funnel.get(key,0)) for key in scout_keys}
        for key in scout_keys:
            funnel[key]=0
        s['wallets']={}
        s['seen']={}
        coverage=s.get('coverage',{})
        s['coverage']={k:v for k,v in coverage.items() if k=='pump_program_stream'}
        # An old scout heartbeat must never make the new discovery authority ready.
        # Fresh market-native stream coverage will advance both fields after warmup.
        s['progress']=0
        s['last_time']=0
    return True


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--db',required=True)
    ap.add_argument('--mode',choices=['synthetic','captured','prospective'],required=True)
    ap.add_argument('--config',required=True)
    ap.add_argument('--tape')
    ap.add_argument('--seconds',type=int,default=60)
    ap.add_argument('--port',type=int,default=8080)
    args=ap.parse_args()
    with open(args.config) as f:
        config=json.load(f)

    discovery_mode=config.get('discovery_mode','market_native' if args.mode=='prospective' else 'scout')
    if args.mode=='prospective':
        if discovery_mode!='market_native':
            ap.error('prospective scout discovery retired; discovery_mode must be market_native')
        if config.get('seeds'):
            ap.error('prospective market-native discovery requires empty seeds')
        if not config.get('discovery_provenance'):
            ap.error('market-native discovery provenance required')
        if ('synthetic' in config.get('discovery_provenance','').lower() or
                'synthetic' in config['valuation_source'].lower()):
            ap.error('synthetic configuration cannot be prospective')
        if args.tape:
            ap.error('prospective mode cannot accept a tape')
    else:
        if not config.get('seed_provenance'):
            ap.error('seed provenance required')
    if not 1<=args.seconds<=3600:
        ap.error('budgeted session must be 1..3600 seconds')

    request_limit=int(config.get('request_limit',240 if args.mode=='prospective' else 120))
    preflight_budget=int(config.get('market_native_preflight_budget',90))
    full_evidence_budget=int(config.get('market_native_full_evidence_budget',20))
    provider_rotation_threshold=int(config.get('market_native_rpc_rotation_threshold',160))
    if args.mode=='prospective':
        if not 40 <= provider_rotation_threshold <= request_limit-40:
            ap.error('market_native_rpc_rotation_threshold must preserve 40 monitoring requests')

    store=Store(args.db,args.mode,config['initial_sol_usd_micros'],config['valuation_source'])
    if args.mode=='prospective':
        _retire_scout_state(store)
    engine=Engine(store,[] if args.mode=='prospective' else config.get('seeds',[]),config.get('related_groups'))
    release=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True).stdout.strip() or 'uncommitted'
    dirty=subprocess.run(['git','status','--porcelain'],capture_output=True,text=True).stdout.strip()
    if dirty:
        release+='-dirty'
    if args.tape:
        print(json.dumps(dict(replay(engine,args.tape),release=release),sort_keys=True))
        store.close()
        return
    if args.mode!='prospective':
        ap.error('offline mode requires --tape')

    published=dict(engine.status(int(time.time())),release=release,
                   discovery_mode='market_native',scout_lane_active=False,
                   scout_storage_active=False)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/live','/ready','/status'):
                self.send_error(404)
                return
            code=503 if self.path=='/ready' and not published['ready'] else 200
            data=json.dumps({'live':True} if self.path=='/live' else published).encode()
            self.send_response(code)
            self.send_header('Content-Type','application/json')
            self.end_headers()
            self.wfile.write(data)
        def log_message(self,*args):
            pass
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    stopping=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopping.set())
    signal.signal(signal.SIGINT,lambda *_:stopping.set())
    stream_thread=None
    try:
        url=primary_rpc_url()
        rpc=new_rpc(limit=request_limit)
        adapter=PumpAdapter(rpc)
        postgrad_adapter=PostGraduationAdapter(rpc,scan_rpc=object())
        pumpswap_runtime=PumpSwapPaperRuntime(store,postgrad_adapter)
        tape=PumpTape()
        ready=threading.Event()
        log_stream=PumpLogStream(url,tape)
        stream_thread=threading.Thread(target=log_stream.run,args=(stopping,ready),daemon=True)
        stream_thread.start()
        market_runtime=MarketNativeRuntime(
            engine,adapter,max(1,args.seconds),
            preflight_budget=preflight_budget,
            full_evidence_budget=full_evidence_budget,
            provider_rotation_threshold=provider_rotation_threshold,
        )
        if not ready.wait(15) or log_stream.error_kind:
            with store.transaction('stream_start_failure'):
                engine.quarantine('stream_continuity_unavailable',int(time.time()))
        cursor=None
        deadline=time.monotonic()+args.seconds
        while time.monotonic()<deadline and not stopping.is_set():
            now=int(time.time())
            _monitor_existing(engine,adapter,now,pumpswap_runtime=pumpswap_runtime)
            if rpc.calls >= provider_rotation_threshold:
                pacer=rpc.read_pacer if hasattr(rpc,'read_pacer') else None
                rpc=new_rpc(limit=request_limit,pacer=pacer)
                adapter=PumpAdapter(rpc)
                postgrad_adapter=PostGraduationAdapter(rpc,scan_rpc=object())
                pumpswap_runtime=PumpSwapPaperRuntime(store,postgrad_adapter)
                market_runtime.replace_adapter(adapter)
            cursor=market_runtime.tick(tape,now,cursor)
            published=dict(engine.status(int(time.time())),release=release,
                           discovery_mode='market_native',scout_lane_active=False,
                           scout_storage_active=False,
                           stream=tape.status(int(time.time())),
                           market_native_discovery=market_runtime.status(),
                           pumpswap_continuation=pumpswap_runtime.status())
            stopping.wait(5)
        print(json.dumps(published,sort_keys=True))
    finally:
        stopping.set()
        if stream_thread is not None:
            stream_thread.join(timeout=3)
        server.shutdown()
        store.close()

if __name__=='__main__':
    main()
