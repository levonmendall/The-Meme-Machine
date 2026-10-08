"""Separately bounded, read-only Model B proof; no funding books or safety override.

Describe is offline. Execute needs the owner's separately granted spending scope.
The existing concurrent-provider blocker is never changed by this diagnostic.
"""
import argparse
from collections import Counter
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.request


class CeilingReached(RuntimeError):pass


def observe_budgeted(budget,observer,kind,value):
    try:budget.delivery(kind,value)
    finally:
        # The stopping frame was already physically received and charged.
        # Capturing it adds no canonical completeness authority.
        observer(kind,value)


class Budget:
    def __init__(self,limits,out):
        required={'wall_seconds','solana_rpc_requests','robinhood_rpc_requests','estimated_rpc_cu',
            'native_delivery_bytes','estimated_native_delivery_cu','storage_bytes','native_errors','steady_seconds'}
        if set(limits)!=required or any(type(v) is not int or v<=0 for v in limits.values()):raise ValueError('explicit_positive_ceiling_contract')
        if limits['wall_seconds']>600 or limits['steady_seconds']>180:raise ValueError('bounded_technical_proof_only')
        self.limits=limits;self.out=out;self.started=time.monotonic();self.lock=threading.Lock()
        self.requests=Counter();self.methods=Counter();self.http=Counter();self.cu=0;self.native_bytes=0;self.native_cu=0
        self.reason=None;self.stop=threading.Event();self.original=urllib.request.urlopen

    def fail(self,reason):
        self.reason=self.reason or reason;self.stop.set();raise CeilingReached(reason)

    def open(self,request,*args,**kwargs):
        from .certify import CU
        from meme_machine.lanes.pons.provider import READ_METHODS
        from urllib.parse import urlsplit
        body=json.loads(request.data);calls=body if isinstance(body,list) else [body]
        host=urlsplit(request.full_url).hostname
        # The original Pons topology uses the official public observation RPC
        # alongside authoritative Alchemy reads. Both spend the Robinhood cap.
        family='solana' if host=='solana-mainnet.g.alchemy.com' else 'robinhood' if host in (
            'robinhood-mainnet.g.alchemy.com','rpc.mainnet.chain.robinhood.com') else None
        if family is None:self.fail('unapproved_provider_endpoint')
        methods=[row['method'] for row in calls]
        if any(m not in (CU if family=='solana' else READ_METHODS) for m in methods):self.fail('non_read_method_or_unestimated_rpc')
        estimate=sum(CU[m] if family=='solana' else 100 for m in methods)
        with self.lock:
            if self.stop.is_set():raise CeilingReached(self.reason or 'bounded_stop')
            if self.requests[family]+len(calls)>self.limits[family+'_rpc_requests']:self.fail(family+'_request_ceiling')
            if self.cu+estimate>self.limits['estimated_rpc_cu']:self.fail('estimated_rpc_cu_ceiling')
            self.requests[family]+=len(calls);self.http[family]+=1;self.cu+=estimate
            self.methods.update(family+':'+m for m in methods)
        # Count every attempted retry/batch element before the physical request.
        return self.original(request,*args,**kwargs)

    def delivery(self,kind,value):
        if kind!='delivery':return
        with self.lock:
            self.native_bytes+=len(value['raw']);self.native_cu=math.ceil(self.native_bytes/512)
            if self.native_bytes>self.limits['native_delivery_bytes']:self.fail('native_delivery_byte_ceiling')
            if self.native_cu>self.limits['estimated_native_delivery_cu']:self.fail('estimated_native_delivery_cu_ceiling')
            # Stop ahead of the allowance by one maximum production frame,
            # rather than discovering the bound only after crossing it.
            from meme_machine.solana_selective_source import MAX_FRAME_BYTES
            if self.limits['native_delivery_bytes']>MAX_FRAME_BYTES and self.native_bytes>=self.limits['native_delivery_bytes']-MAX_FRAME_BYTES:
                self.fail('native_delivery_inflight_margin_stop')

    def snapshot(self):
        with self.lock:
            return dict(requests=dict(self.requests),physical_http_attempts=dict(self.http),methods=dict(self.methods),
                estimated_rpc_cu=self.cu,native_delivery_bytes=self.native_bytes,estimated_native_delivery_cu=self.native_cu,
                estimate_basis='published Solana method weights; Robinhood planning weight 100/request; native planning weight ceil(bytes/512)',
                billed_provider_cu='UNMEASURED',reason=self.reason,limits=self.limits)

    def watch(self,c):
        while not self.stop.wait(.1):
            total=0;seen=set()
            for p in self.out.rglob('*'):
                try:
                    stat=p.stat();key=(stat.st_dev,stat.st_ino)
                    if p.is_file() and key not in seen:total+=stat.st_size;seen.add(key)
                except FileNotFoundError:pass
            reason=('wall_time_ceiling' if time.monotonic()-self.started>=self.limits['wall_seconds']-10 else
                'storage_ceiling' if total>=self.limits['storage_bytes'] else
                'native_error_ceiling' if len(c.transport.native_errors)>=self.limits['native_errors'] else None)
            if reason:self.reason=reason;self.stop.set()
        c.worker_stop.set()


def pons(out,endpoint,budget):
    """Use production discovery/authentication and read-only position functions.

    The Survivor controller constructor is intentionally unused: no native
    monetary book exists in this proof. Its evidence methods remain unchanged.
    A cold seven-day startup remains mandatory and may exhaust the approved cap.
    """
    from meme_machine.lanes.pons import BoundaryError
    from meme_machine.lanes.pons.pons_selective_cohort import _discovery,_discovery_curve_events
    from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext,evaluate_candidate
    from meme_machine.lanes.pons.pons_natural_observation import _latest_header
    from meme_machine.lanes.pons.pons_selective_paper import _wait_curve_quote,paper_rpc,_gas_units,STRATEGY_CAPITAL_QUOTE
    from meme_machine.lanes.pons.provider_admission import position_work
    from meme_machine.lanes.pons.evidence import Store
    from meme_machine.lanes.pons.pons_survivor_runtime import Runtime,Quotes,POLICY_HASH
    from meme_machine.lanes.pons.pons_history import PonsHistory
    from meme_machine.runtime.robinhood.plane import Plane
    from meme_machine.lanes.pons.pons_attempts import Attempts
    out.mkdir();survivor=object.__new__(Runtime);survivor.root=out;survivor.endpoint=endpoint;survivor.rpc=None
    survivor.history=PonsHistory(out/'history.sqlite',policy=POLICY_HASH);survivor.plane=Plane(out/'candidates.sqlite')
    survivor.attempts=Attempts(survivor.plane);survivor.current=None
    context=SelectiveEvidenceContext(endpoint);rpc=None;cursor=None;results=[];positions=[];coverage=[];errors=[];current=None;tape=[]
    evidence=Store(out/'position-quotes.sqlite')
    @position_work
    def current_tick(candidate):
        position_rpc=paper_rpc(endpoint)
        quote,_,_=_wait_curve_quote(position_rpc,candidate,'sell',candidate['quote']['tokens_out'],
            _gas_units(candidate['receipt']),evidence,'provider-proof-current-exit',int(time.time()),
            seconds=5,local_freshness=True)
        return quote.amount_out>0
    try:
        while not budget.stop.is_set():
            try:
                if rpc is None or rpc.used>150:rpc=_discovery(endpoint)
                header=_latest_header(rpc);top=int(header['number'],16)
                if cursor is None:cursor=max(0,top-1)
                end=min(top,cursor+40)
                if end>cursor:
                    events=_discovery_curve_events(rpc,cursor+1,end)
                    coverage.append(dict(first=cursor+1,last=end,events=len(events)));cursor=end
                    tape.extend(events)
                    for event in events:
                        wall=time.time();start=time.monotonic()
                        try:
                            result=evaluate_candidate(endpoint,event,list(tape),strategy_capital_quote=STRATEGY_CAPITAL_QUOTE,evidence_context=context,
                                evidence_observed_at=wall,evidence_observed_monotonic=start)
                            results.append(dict(at=wall,seconds=time.monotonic()-start,token=result['token'],
                                current_evidence_complete=result.get('vector',{}).get('complete',False)))
                            if result.get('candidate'):current=result['candidate']
                        except BoundaryError as error:results.append(dict(at=wall,seconds=time.monotonic()-start,reason=str(error)))
                # Both native evidence domains receive bounded scheduling time.
                if current is not None:
                    started=time.monotonic()
                    try:
                        ready=current_tick(current)
                        positions.append(dict(regime='pons_current',seconds=time.monotonic()-started,ready=ready))
                    except BoundaryError as error:positions.append(dict(regime='pons_current',seconds=time.monotonic()-started,reason=str(error),ready=False))
                survivor._provider();survivor.discover()
                for row in survivor.history.rows():
                    if row['state']=='retired':continue
                    started=time.monotonic()
                    try:
                        survivor._increment(row,min(top,row['block']+39))
                        state=survivor.fresh_state(row['id']);quote=survivor.exit_quote(1_000_000_000)
                        positions.append(dict(regime='pons_survivor',seconds=time.monotonic()-started,
                            ready=bool(quote),block=state['block']))
                    except BoundaryError as error:positions.append(dict(regime='pons_survivor',seconds=time.monotonic()-started,reason=str(error),ready=False))
            except CeilingReached:break
            except BoundaryError as error:errors.append(dict(type='BoundaryError',reason=str(error)))
            budget.stop.wait(.5)
    except Exception as error:
        # Unexpected errors carry a type only, never an endpoint-bearing repr.
        errors.append(dict(type=type(error).__name__,reason='unexpected_provider_proof_error'))
    finally:
        status=dict(discovery_cursor=cursor,survivor_discovery_cursor=survivor.history.get_meta('discovery_block'),
            survivor_bootstrap=survivor.history.get_meta('discovery_bootstrap'),coverage=coverage,
            candidates=results,position_equivalence=positions,errors=errors,
            sizing_context='original nominal technical input only; no production economic acceptance or funding',
            ramses_acquisition_calls=0,full_provider_coverage_certified=False)
        (out/'result.json').write_text(json.dumps(status,indent=2)+'\n')
        survivor.history.close();survivor.plane.close();evidence.close()


async def child(args,limits):
    from .final_mixed import FinalMixed,reconcile
    from . import certify
    from meme_machine.solana_evidence_service import serve
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False);scratch=out/'state';scratch.mkdir()
    if len(os.fsencode(str(scratch/'canonical.sqlite')+'.sock'))>=108:
        raise ValueError('disposable_unix_socket_path_too_long')
    os.environ['TMPDIR']=str(scratch)
    env={}
    for line in Path(args.env).read_text().splitlines():
        parts=shlex.split(line)
        if len(parts)==1 and '=' in parts[0]:
            k,v=parts[0].split('=',1)
            if k in ('MM_SOLANA_READ_RPC_URL','MM_SOLANA_YELLOWSTONE_TOKEN','MM_ROBINHOOD_READ_RPC_URL'):env[k]=v
    os.environ.update(env,MM_PROVIDER_GOVERNOR_DB=str(out/'governor.sqlite'),MM_PROVIDER_DB=str(out/'robinhood-provider.sqlite'),
        MM_OPERATIONAL_PHASE='BOUNDED_PROVIDER_PROOF',
        MM_RPC_CACHE_DB=str(out/'robinhood-evidence.sqlite'),MM_ROBINHOOD_STATE_DIR=str(out/'pons'),
        MM_SOLANA_EVIDENCE_PLANE_DB=str(scratch/'canonical.sqlite'),MM_SOLANA_CANDIDATE_HISTORY_DB=str(out/'candidate.sqlite'))
    # No production monetary path or epoch is passed into the proof.
    for key in ('MM_STATE_ROOT','MM_PORTFOLIO_ACCOUNTING_DB','MM_DIRECTIONAL_SLEEVE_DB','MM_DIRECTIONAL_COHORT_ID'):os.environ.pop(key,None)
    budget=Budget(limits,out);urllib.request.urlopen=budget.open
    from meme_machine.lanes.pons import provider as robinhood_transport
    robinhood_transport.urlopen=budget.open
    c=FinalMixed(out,limits['steady_seconds'],env);c.position_families=('pump','pumpswap');c.meter.install()
    for name in ('engineering/solana_capacity/pump_pons_proof.py',
            'meme_machine/lanes/pons/pons_survivor_runtime.py',
            'meme_machine/lanes/pons/pons_selective_acquisition.py',
            'meme_machine/lanes/pons/pons_selective_cohort.py',
            'meme_machine/lanes/pons/pons_selective_paper.py',
            'meme_machine/lanes/pons/provider.py'):
        c.source_hashes[name]=hashlib.sha256(Path(name).read_bytes()).hexdigest()
    native_observer=c.source.observer
    def observed(kind,value):
        try:observe_budgeted(budget,native_observer,kind,value)
        except CeilingReached:
            stop.set();c.worker_stop.set();raise
        if kind=='native_error' and len(c.transport.native_errors)>=limits['native_errors']:
            budget.reason=budget.reason or 'native_error_ceiling';budget.stop.set()
    c.source.observer=observed;stop=asyncio.Event()
    watcher=threading.Thread(target=budget.watch,args=(c,),daemon=True);watcher.start()
    robin=threading.Thread(target=pons,args=(out/'pons',env['MM_ROBINHOOD_READ_RPC_URL'],budget),daemon=True);robin.start()
    async def stop_bridge():
        while not budget.stop.is_set():await asyncio.sleep(.1)
        stop.set()
    bridge=asyncio.create_task(stop_bridge())
    try:
        await asyncio.to_thread(c.rpc.validate_network)
        await serve(scratch/'canonical.sqlite',c.config.http_url,repair_rpc=c.rpc,stop=stop,source_driver=c)
    except Exception as error:c.errors.append(dict(task='bounded_proof',type=type(error).__name__,reason=certify.safe_reason(error)))
    finally:
        budget.stop.set();stop.set();c.worker_stop.set();bridge.cancel();robin.join(timeout=5)
        c.write();c.meter.close();c.transport.close()
        (out/'ceilings.json').write_text(json.dumps(budget.snapshot(),indent=2)+'\n')
        (out/'READINESS.json').write_text(json.dumps(dict(status='TECHNICAL_EVIDENCE_REQUIRES_REVIEW',
            financial_books_opened=0,deployed_epoch_modified=False,paused_workers=0,
            combined_position_and_candidate_provider_latency_not_certified=True),indent=2)+'\n')
        reconcile(out)


def main():
    p=argparse.ArgumentParser();p.add_argument('--limits',required=True);p.add_argument('--output');p.add_argument('--env',default='/etc/meme-machine/paper.env')
    p.add_argument('--execute',action='store_true');p.add_argument('--child',action='store_true');a=p.parse_args()
    limits=json.loads(Path(a.limits).read_text());Budget(limits,Path(a.output or '.'))
    if not a.execute and not a.child:print(json.dumps(dict(mode='OFFLINE_DESCRIPTION',limits=limits,provider_calls=0),indent=2));return
    if not a.output:raise SystemExit('disposable_output_required')
    if a.child:asyncio.run(child(a,limits));return
    command=[sys.executable,'-m',__spec__.name,'--child','--limits',a.limits,'--output',a.output,'--env',a.env]
    process=subprocess.Popen(command,start_new_session=True)
    try:process.wait(timeout=limits['wall_seconds']-5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
    out=Path(a.output)
    if out.exists():(out/'process.json').write_text(json.dumps(dict(exit_code=process.returncode,hard_wall_seconds=limits['wall_seconds']))+'\n')
    raise SystemExit(process.returncode or 0)


if __name__=='__main__':main()
