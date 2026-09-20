"""Run one pinned lane once with observation-only instrumentation.

No wrapper retries a lane or changes qualification, clocks, finality, ledger state,
or errors. The original lane entrypoint remains authoritative. Every checkpoint
and public RPC response is retained in a run-local append-only journal/archive.
"""
from __future__ import annotations
import argparse
import dataclasses
import functools
import gzip
import importlib
import json
import os
import re
from pathlib import Path
import sys
import threading
import time
import uuid
from collections import Counter
from certification.journal import Journal, canonical, digest
from certification.governor import Governor

class Observer:
    def __init__(self, root, lane, policy):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.lane,self.policy=lane,policy
        self.lock=threading.RLock();self.sequence=0;self.methods=Counter()
        self.latencies=[];self.errors=Counter();self.started=time.monotonic()
        self.journal=Journal(self.root/'telemetry.sqlite')
        self.raw=gzip.open(self.root/'rpc-evidence.jsonl.gz','ab')
        self.archive_ns=0;self.requests=0;self.raw_records=0;self.provider_sessions={}
        self.last_progress=None;self.last_report=None
        self.governor=Governor(os.environ["MM_CERT_GOVERNOR_DB"])
        self.context=threading.local()

    def event(self, kind, body):
        with self.lock:
            self.sequence+=1
            identity=f'{os.getpid()}:{self.sequence}'
            self.journal.append(self.lane,identity,kind,body)
            return identity

    def checkpoint(self, body, phase):
        # Called by the lane's progress path, never by a timer pretending health.
        self.last_progress=time.monotonic()
        if self.lane=='pons':
            path=Path('pons-selective-continuation-v1-cohort/pons-selective-cohort-capital.sqlite')
            if path.exists():
                from robinhood_research.pons_selective_capital import CohortCapital
                from robinhood_research.pons_selective_paper import STRATEGY_CAPITAL_QUOTE
                body=dict(body,cohort_accounting=CohortCapital(path,STRATEGY_CAPITAL_QUOTE).reconcile())
        self.last_report=body
        self.event('checkpoint', dict(phase=phase,report=body,policy_hash=self.policy))
        self.status(phase,body)

    def status(self, phase, body=None):
        with self.lock:
            if body is None:body=self.last_report
            lat=sorted(self.latencies)
            quant=lambda f: None if not lat else lat[min(len(lat)-1,int((len(lat)-1)*f))]
            data=dict(lane=self.lane,pid=os.getpid(),process_nonce=PROCESS_NONCE,
                      phase=phase,policy_hash=self.policy,wall_time=time.time(),
                      uptime_seconds=time.monotonic()-self.started,
                      last_progress_monotonic=self.last_progress,
                      provider_requests=self.requests,method_counts=dict(self.methods),
                      errors=dict(self.errors),provider_session_count=len(self.provider_sessions),
                      rpc_latency_seconds=dict(p50=quant(.5),p95=quant(.95),p99=quant(.99)),
                      telemetry_archive_seconds=self.archive_ns/1e9,
                      report=body,
                      terminal_monotonic=time.monotonic() if phase in ("returned","failed") else None)
            raw=canonical(data);tmp=self.root/'status.json.tmp';tmp.write_text(raw);os.replace(tmp,self.root/'status.json')

    def prioritize(self, module, name):
        original=getattr(module,name)
        @functools.wraps(original)
        def run(*args,**kwargs):
            previous=getattr(self.context,'priority',50)
            self.context.priority=0
            try:return original(*args,**kwargs)
            finally:self.context.priority=previous
        setattr(module,name,run)

    def wrap_transport(self, cls, name, *, batch=False, solana=False):
        original=getattr(cls,name)
        observer=self
        @functools.wraps(original)
        def observed(instance,*args,**kwargs):
            started=time.monotonic_ns();result=None;error=None;http_status=None;rpc_error_codes=[];transport_started=None
            # Use only opaque session identities. Never archive endpoint URLs.
            with observer.lock:
                if not hasattr(instance,'_certification_session_id'):
                    instance._certification_session_id=str(uuid.uuid4())
                session=instance._certification_session_id
                observer.provider_sessions[session]=True
            network="solana" if solana else "robinhood"
            queue_wait=None
            if solana:
                request=args[0]
                calls=request if isinstance(request,list) else [request]
                methods=[x.get('method','unknown') for x in calls]
                wire=calls
            elif batch:
                wire=list(args[0]);methods=[x[0] for x in wire]
            else:
                methods=[args[0]];wire=[(args[0],args[1])]
            try:
                queue_wait=(observer.governor.acquire(network,observer.lane,getattr(observer.context,"priority",50))
                            if solana or not os.environ.get("MM_CERTIFICATION_PROVIDER_DB") else None)
                transport_started=time.monotonic_ns()
                result=original(instance,*args,**kwargs)
                http_status=200
                if solana:
                    replies=result if isinstance(result,list) else [result]
                    rpc_error_codes=[x['error'].get('code') for x in replies
                                     if isinstance(x,dict) and isinstance(x.get('error'),dict)]
                return result
            except BaseException as exc:
                message=str(exc)
                http_status=getattr(exc,'code',None)
                match=re.fullmatch(r'provider_http_(\d+)',message)
                if match:http_status=int(match[1])
                match=re.fullmatch(r'provider_rpc_(-?\d+)',message)
                if match:rpc_error_codes=[int(match[1])]
                # Only stable code-shaped errors are emitted; no free-form URLs.
                error=message if message.replace('_','').replace('-','').isalnum() and len(message)<160 else type(exc).__name__
                raise
            finally:
                elapsed=(time.monotonic_ns()-started)/1e9
                with observer.lock:
                    observer.raw_records+=1
                    transport_elapsed=None
                    if transport_started is not None:
                        transport_elapsed=(time.monotonic_ns()-transport_started)/1e9
                        observer.requests+=1;observer.methods.update(methods);observer.latencies.append(transport_elapsed)
                    if error:
                        observer.errors[error]+=1
                    if (http_status==429 or 429 in rpc_error_codes or (error and "429" in error)) and (solana or not os.environ.get("MM_CERTIFICATION_PROVIDER_DB")):
                        observer.governor.rate_limited(network)
                    before=time.monotonic_ns()
                    record=dict(sequence=observer.raw_records,lane=observer.lane,session=session,
                                transport_attempted=transport_started is not None,transport_duration_seconds=transport_elapsed,
                                observed_at_ns=time.time_ns(),duration_seconds=elapsed,
                                request=wire,response=result,error=error,queue_wait_seconds=queue_wait,
                                http_status=http_status,json_rpc_error_codes=rpc_error_codes,
                                retry_count=getattr(instance,"retry_count",getattr(instance,"retries",None)),
                                authentication='raw_transport_response_requires_lane_verification')
                    observer.raw.write((canonical(record)+'\n').encode());observer.raw.flush();os.fsync(observer.raw.fileno())
                    observer.archive_ns+=time.monotonic_ns()-before
                    observer.event('rpc_transport',dict(sequence=observer.raw_records,session=session,transport_attempted=transport_started is not None,
                        methods=methods,duration_seconds=elapsed,transport_duration_seconds=transport_elapsed,error=error,http_status=http_status,
                        json_rpc_error_codes=rpc_error_codes,queue_wait_seconds=queue_wait,raw_hash=digest(record)))
        setattr(cls,name,observed)

PROCESS_NONCE=str(uuid.uuid4())

def policy_for(lane):
    if lane=='pump':
        from meme_machine.pump_acceleration_strategy import policy_hash
        return policy_hash()
    if lane=='meteora':
        return digest(json.loads(Path('SOLANA_DLMM_INDEPENDENT_V1.json').read_text()))
    name='pons_selective_continuation' if lane=='pons' else 'ramses_strategy'
    return importlib.import_module('robinhood_research.'+name).POLICY_HASH


def main():
    p=argparse.ArgumentParser();p.add_argument('--lane',required=True);p.add_argument('--output',required=True)
    p.add_argument('--policy-hash',required=True);p.add_argument('--seconds',type=int,required=True)
    args=p.parse_args()
    # Lane source precedes the certification repository, including its tests package.
    sys.path.insert(0,os.getcwd())
    actual=policy_for(args.lane)
    if actual!=args.policy_hash:raise ValueError('frozen_policy_hash_changed')
    observer=Observer(args.output,args.lane,actual)
    observer.checkpoint(dict(source_sha=os.environ['MM_CERT_SOURCE_SHA']),'initializing')
    if args.lane in ('pump','meteora'):
        from meme_machine.solana_read_rpc import _ReadOnlyFailoverMixin
        observer.wrap_transport(_ReadOnlyFailoverMixin,'_http',solana=True)
    else:
        from robinhood_research.provider import Rpc
        observer.wrap_transport(Rpc,'_http')
        observer.wrap_transport(Rpc,'_http_batch',batch=True)
    try:
        if args.lane=='pump':
            os.environ['MM_PUMP_ACCELERATION_DISCOVERY_SECONDS']=str(args.seconds)
            module=importlib.import_module('tests.pump_acceleration_natural_prospective')
            observer.prioritize(module,"_fill_pending")
            original=module._save
            def save(report):
                original(report);observer.checkpoint(report,'lane_checkpoint')
            module._save=save;module.main()
        elif args.lane=='meteora':
            module=importlib.import_module('tests.solana_dlmm_independent_v1')
            observer.prioritize(module,"_lifecycle")
            original=module._atomic_checkpoint
            def checkpoint(report,stage,*a,**kw):
                result=original(report,stage,*a,**kw)
                observer.checkpoint(report,stage);return result
            module._atomic_checkpoint=checkpoint
            module.run_live(target=6,max_attempted=48,max_runtime_seconds=args.seconds)
        elif args.lane=='pons':
            os.environ['MM_PONS_SELECTIVE_DISCOVERY_SECONDS']=str(args.seconds)
            module=importlib.import_module('robinhood_research.pons_selective_cohort')
            observer.prioritize(module,"run_lifecycle")
            original=module._checkpoint
            def checkpoint(result,**kw):
                value=original(result,**kw);observer.checkpoint(result,kw['phase']);return value
            module._checkpoint=checkpoint
            result=module.run(os.environ.get('MM_ROBINHOOD_READ_RPC_URL',''))
            module._atomic_json(module.REPORT,result)
            observer.checkpoint(result,'lane_result')
        else:
            module=importlib.import_module('robinhood_research.ramses_extended_test')
            # Observe completed authentic scans and frontier checks without replacing
            # the discovery or lifecycle algorithm. Startup/scan stalls stay visible.
            observer.prioritize(module,"run_connected")
            observer.prioritize(module,"_forced_machinery")
            original=module.scan
            def scan(*a,**kw):
                result=original(*a,**kw);observer.checkpoint(module._screen_summary(result),'authenticated_scan');return result
            module.scan=scan
            gate=module._frontier_scan_gate
            def frontier(*a,**kw):
                result=gate(*a,**kw);observer.checkpoint(dict(frontier_gate=result),'frontier_progress');return result
            module._frontier_scan_gate=frontier
            os.environ['MM_ROBINHOOD_RAMSES_EXTENDED_DISCOVERY_SECONDS']=str(args.seconds)
            module.main()
        observer.event('process_terminal',dict(status='returned',policy_hash=policy_for(args.lane)))
        observer.status('returned')
    except BaseException as exc:
        observer.event('process_terminal',dict(status='failed',exception_type=type(exc).__name__))
        observer.status('failed')
        raise
    finally:
        observer.raw.close();observer.journal.close()

if __name__=='__main__':main()
