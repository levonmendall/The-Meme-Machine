"""Bounded paper experiment; one writer loop, read-only HTTP snapshot publication."""
import argparse
import json
import os
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .engine import Engine
from .provider import RPC, PumpAdapter, Unavailable
from .store import Store


def tick(engine, adapter, now):
    s=engine.store.state
    # Existing exposure always comes first, independently of wallet activity.
    for mint,p in list(s['positions'].items()):
        if now>=p['next_monitor']:
            try:
                snap=adapter.snapshot(mint,now,priority=True)
            except (Unavailable,ValueError):
                snap={}
            engine.monitor(mint,snap,int(time.time()))
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
                market,covered=adapter.history(snap['pool'],now)
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
                           infrastructure_spend_usd=0,provider_spend_usd=0 if getattr(adapter.rpc,'url',None)=='https://api.mainnet-beta.solana.com' else None)


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
    if not config.get('seed_provenance'):
        ap.error('seed provenance required')
    if args.mode=='prospective' and ('synthetic' in config['seed_provenance'].lower() or 'synthetic' in config['valuation_source'].lower()):
        ap.error('synthetic configuration cannot be prospective')
    if args.mode=='prospective' and args.tape:
        ap.error('prospective mode cannot accept a tape')
    if not 1<=args.seconds<=3600:
        ap.error('budgeted session must be 1..3600 seconds')
    store=Store(args.db,args.mode,config['initial_sol_usd_micros'],config['valuation_source'])
    engine=Engine(store,config['seeds'],config.get('related_groups'))
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
    published=dict(engine.status(int(time.time())),release=release)
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
    try:
        rpc=RPC(os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com'),limit=config.get('request_limit',120))
        adapter=PumpAdapter(rpc)
        deadline=time.monotonic()+args.seconds
        while time.monotonic()<deadline and not stopping.is_set():
            now=int(time.time())
            tick(engine,adapter,now)
            published=dict(engine.status(int(time.time())),release=release)
            stopping.wait(5)
        print(json.dumps(published,sort_keys=True))
    finally:
        server.shutdown()
        store.close()

if __name__=='__main__':
    main()
