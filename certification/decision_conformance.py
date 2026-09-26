"""Bounded decision records and independent, offline frozen-function replay.

Only named pure strategy functions are eligible. No pickle, arbitrary callable,
provider I/O or native ledger writes are permitted during replay.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import dataclasses
from decimal import Decimal
from fractions import Fraction
import functools
import hashlib
import importlib
import inspect
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

FUNCTIONS={
 'pump':{'meme_machine.pump_acceleration_strategy':('qualify','entry_signal_persistence','exit_decision'),
     'meme_machine.pump_acceleration_paper':('PumpAccelerationPaperLifecycle.mark',)},
 'pons':{'robinhood_research.pons_selective_continuation':(
     'qualification_vector','entry_signal_persistence','pregraduation_action',
     'post_graduation_vector','runner_action','breakout_vector','reentry_regime_reset')},
 'meteora':{'tests.solana_dlmm_independent_v1':('qualify','_segment_exit','_eligible_exit_reasons')},
 'ramses':{'robinhood_research.ramses_strategy':('classify_pool','controller_action','decompose_pnl')},
}
SURVIVOR_FUNCTIONS={
 'pump':{'meme_machine.pumpswap_survivor':('evaluate_entry',),
         'certification.survivor_risk':('mark',)},
 'pons':{'robinhood_research.pons_postgrad_survivor':('evaluate_entry',),
         'certification.survivor_risk':('mark',)},
}
for _lane,_modules in SURVIVOR_FUNCTIONS.items():FUNCTIONS[_lane].update(_modules)
DATA_MODULES=frozenset(('meme_machine.pump_acceleration_strategy',
    'meme_machine.pump_acceleration_paper','meme_machine.dlmm_tape',
    'robinhood_research.pons','robinhood_research.pons_selective_continuation',
    'robinhood_research.pons_v2'))
MAX_BYTES=64*1024*1024
MAX_RECORD_BYTES=4*1024*1024
_CAPTURE_CONTEXT=threading.local()

@contextmanager
def restoring_recorded_state():
    """Journal restoration verifies old decisions; it is not a new live action."""
    prior=getattr(_CAPTURE_CONTEXT,'restoring',False);_CAPTURE_CONTEXT.restoring=True
    try:yield
    finally:_CAPTURE_CONTEXT.restoring=prior

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def encode(value):
    if value is None or type(value) in (bool,int,str):return value
    if type(value) is float:
        if not math.isfinite(value):return {'$float':str(value)}
        return value
    if isinstance(value,Fraction):return {'$fraction':[value.numerator,value.denominator]}
    if isinstance(value,Decimal):return {'$decimal':str(value)}
    if (type(value).__module__=='meme_machine.pump_acceleration_paper' and
            type(value).__name__=='PumpAccelerationPaperLifecycle'):
        # The decision is replayed with no book. Native economic transitions have
        # a separate immutable-ledger replay, and may never be re-executed here.
        return {'$pump_lifecycle':encode({k:v for k,v in vars(value).items() if k not in ('book','sleeve')})}
    if dataclasses.is_dataclass(value) and not isinstance(value,type):
        cls=type(value)
        if cls.__module__ not in DATA_MODULES:raise TypeError('unsupported_decision_dataclass')
        return {'$dataclass':[cls.__module__,cls.__name__,
            {f.name:encode(getattr(value,f.name)) for f in dataclasses.fields(value)}]}
    if isinstance(value,dict):return {'$map':[[encode(k),encode(v)] for k,v in value.items()]}
    if isinstance(value,list):return [encode(v) for v in value]
    if isinstance(value,tuple):return {'$tuple':[encode(v) for v in value]}
    if isinstance(value,(set,frozenset)):
        return {'$set':sorted((encode(v) for v in value),key=canonical),
                'frozen':isinstance(value,frozenset)}
    raise TypeError('unsupported_decision_input:'+type(value).__name__)

def decode(value):
    if isinstance(value,list):return [decode(v) for v in value]
    if not isinstance(value,dict):return value
    if '$map' in value:return {decode(k):decode(v) for k,v in value['$map']}
    if '$tuple' in value:return tuple(decode(v) for v in value['$tuple'])
    if '$set' in value:return (frozenset if value.get('frozen') else set)(decode(v) for v in value['$set'])
    if '$fraction' in value:return Fraction(*value['$fraction'])
    if '$decimal' in value:return Decimal(value['$decimal'])
    if '$float' in value:
        if value['$float'] not in ('inf','-inf','nan'):raise ValueError('invalid_decision_float')
        return float(value['$float'])
    if '$pump_lifecycle' in value:
        cls=getattr(importlib.import_module('meme_machine.pump_acceleration_paper'),'PumpAccelerationPaperLifecycle')
        instance=cls.__new__(cls);instance.__dict__.update(decode(value['$pump_lifecycle']));instance.book=None;instance.sleeve=None
        return instance
    if '$dataclass' in value:
        module,name,fields=value['$dataclass']
        if module not in DATA_MODULES or not name.isidentifier():raise ValueError('unsafe_decision_type')
        cls=getattr(importlib.import_module(module),name)
        if not dataclasses.is_dataclass(cls):raise ValueError('unsafe_decision_type')
        return cls(**{k:decode(v) for k,v in fields.items()})
    raise ValueError('unknown_decision_encoding')

def _identities(value):
    """Inputs remain authoritative; these labels help navigate records."""
    found={}
    def walk(v,depth=0):
        if depth>6:return
        if dataclasses.is_dataclass(v):v=dataclasses.asdict(v)
        if isinstance(v,dict):
            for k,item in v.items():
                if k in ('mint','token','pool','market','id','observed_at','asof','now',
                         'evidence_available_at','evidence_observed_at','entry_timestamp'):
                    if isinstance(item,(str,int,float)) or item is None:found.setdefault(k,item)
                if isinstance(item,(dict,list,tuple)):walk(item,depth+1)
        elif isinstance(v,(list,tuple)):
            for item in v[:8]:walk(item,depth+1)
    walk(value)
    return found

class Recorder:
    def __init__(self,output,lane,policy_hash):
        self.output=Path(output);self.output.mkdir(parents=True,exist_ok=True)
        self.lane=lane;self.policy_hash=policy_hash;self.lock=threading.RLock()
        self.authority=json.loads(Path(__file__).with_name('sources.json').read_text())['lanes'].get(lane,{})
        self.count=0;self.bytes=0;self.failures=[];self.overhead=0.;self.previous='0'*64
        self.path=self.output/'decision-trace.jsonl'
        if self.path.exists():raise ValueError('decision_trace_already_exists')
        self.handle=self.path.open('x',encoding='utf-8')
        self.started_at=time.time()
    def wrap(self,module,name):
        owner=module
        parts=name.split('.')
        for part in parts[:-1]:owner=getattr(owner,part)
        original=getattr(owner,parts[-1]);signature=inspect.signature(original)
        @functools.wraps(original)
        def recorded(*args,**kwargs):
            if getattr(_CAPTURE_CONTEXT,'restoring',False):return original(*args,**kwargs)
            began=time.perf_counter();record=None
            try:
                bound=signature.bind(*args,**kwargs);bound.apply_defaults()
                record=dict(schema='frozen-decision-v1',lane=self.lane,
                    runtime_sha=os.environ.get('MM_CERT_INTEGRATION_SHA') or os.environ.get('GITHUB_SHA'),
                    source_sha=os.environ.get('MM_CERT_SOURCE_SHA') or self.authority.get('source_sha'),
                    strategy_version=self.authority.get('strategy_version'),policy_hash=self.policy_hash,
                    function=module.__name__+':'+name,at=time.time(),
                    inputs=encode(bound.arguments),identity=_identities(bound.arguments))
            except Exception as exc:self.failure('capture:'+type(exc).__name__)
            capture_seconds=time.perf_counter()-began
            try:
                result=original(*args,**kwargs)
            except Exception as exc:
                if record is not None:
                    record['exception']=type(exc).__name__+':'+str(exc)
                    self.append(record,capture_seconds)
                raise
            if record is not None:
                try:
                    post_started=time.perf_counter()
                    record['result']=encode(result)
                    record['inputs_after']=encode(bound.arguments)
                    self.append(record,capture_seconds+time.perf_counter()-post_started)
                except Exception as exc:self.failure('result:'+type(exc).__name__)
            return result
        # Replace already-imported aliases as well as future imports. Never wrap
        # a different function merely because it has the same attribute name.
        for loaded in list(sys.modules.values()):
            if loaded is None:continue
            ns=getattr(loaded,'__dict__',{})
            if not str(ns.get('__name__','')).startswith(('meme_machine.','robinhood_research.','tests.')):continue
            for key,value in list(ns.items()):
                if value is original:ns[key]=recorded
        setattr(owner,parts[-1],recorded)
        return recorded
    def failure(self,reason):
        with self.lock:
            if reason not in self.failures:self.failures.append(reason)
            self.status(False)
    def append(self,record,capture_seconds):
        began=time.perf_counter()
        with self.lock:
            record.update(sequence=self.count+1,previous=self.previous)
            checksum=digest(record);line=canonical(dict(record,sha256=checksum))+'\n'
            size=len(line.encode())
            if size>MAX_RECORD_BYTES or self.bytes+size>MAX_BYTES:
                self.failure('decision_trace_capacity');return
            self.handle.write(line);self.handle.flush()
            self.count+=1;self.bytes+=size;self.previous=checksum
            self.overhead+=capture_seconds+time.perf_counter()-began
    def status(self,complete):
        row=dict(schema='frozen-decision-trace-status-v1',lane=self.lane,
            policy_hash=self.policy_hash,complete=complete,failures=list(self.failures),
            decisions=self.count,bytes=self.bytes,sha256=self.previous,
            capture_overhead_seconds=self.overhead,started_at=self.started_at,
            updated_at=time.time(),provider_calls_added=0,byte_limit=MAX_BYTES)
        p=self.output/'decision-trace-status.json';tmp=p.with_suffix('.tmp')
        tmp.write_text(canonical(row)+'\n');os.replace(tmp,p)
        return row
    def close(self):
        with self.lock:
            self.handle.flush();os.fsync(self.handle.fileno());self.handle.close()
            return self.status(True)

def install(output,lane,policy_hash):
    recorder=Recorder(output,lane,policy_hash)
    for module,names in FUNCTIONS[lane].items():
        if module in SURVIVOR_FUNCTIONS.get(lane,{}) and os.environ.get('MM_DIRECTIONAL_COMPOSITE_REQUIRED')!='1':
            continue
        target=importlib.import_module(module)
        for name in names:recorder.wrap(target,name)
    recorder.status(False)
    return recorder

def replay(path,*,lane,policy_hash,runtime_sha):
    path=Path(path);status_path=path.with_name('decision-trace-status.json')
    if not path.exists() or not status_path.exists():
        return dict(status='unknown',checked=0,failures=[],unavailable=['decision_inputs_not_preserved'])
    status=json.loads(status_path.read_text());failures=[];checked=0;previous='0'*64
    authority=json.loads(Path(__file__).with_name('sources.json').read_text())['lanes'].get(lane,{})
    function_counts={}
    # Import native types before replacing socket.socket: ssl defines a subclass
    # during import. Importing a module does not invoke its market runner.
    for module in FUNCTIONS[lane]:importlib.import_module(module)
    # Offline sandbox: these functions have no reason to contact a provider.
    import socket
    def denied(*a,**k):raise RuntimeError('decision_replay_network_forbidden')
    original=socket.socket;socket.socket=denied
    started=time.perf_counter()
    try:
        with path.open() as f:
            for line in f:
                row=json.loads(line);observed_hash=row.pop('sha256')
                if (row.get('previous')!=previous or digest(row)!=observed_hash or
                    row.get('sequence')!=checked+1):raise ValueError('decision_trace_chain')
                previous=observed_hash
                if row['lane']!=lane or row['policy_hash']!=policy_hash or row['runtime_sha']!=runtime_sha:
                    raise ValueError('decision_trace_identity')
                if any(row.get(k)!=authority.get(k) for k in ('source_sha','strategy_version')):
                    raise ValueError('decision_trace_source_identity')
                module,name=row['function'].split(':')
                if name not in FUNCTIONS[lane].get(module,()):raise ValueError('decision_callable_not_allowed')
                function=importlib.import_module(module)
                for part in name.split('.'):function=getattr(function,part)
                arguments=decode(row['inputs'])
                bound=inspect.signature(function).bind_partial();bound.arguments.update(arguments)
                actual_exception=None;actual=None
                try:actual=encode(function(*bound.args,**bound.kwargs))
                except Exception as exc:actual_exception=type(exc).__name__+':'+str(exc)
                checked+=1
                function_counts[row['function']]=function_counts.get(row['function'],0)+1
                if (actual_exception!=row.get('exception') or
                    (actual_exception is None and (actual!=row['result'] or encode(arguments)!=row['inputs_after']))):
                    failures.append(dict(sequence=row['sequence'],function=row['function'],
                        candidate=row.get('identity'),classification='strategy_conformance_failure'))
        if status.get('sha256')!=previous or status.get('decisions')!=checked:
            raise ValueError('decision_trace_incomplete')
        unavailable=list(status.get('failures') or [])
        if not status.get('complete'):unavailable.append('decision_trace_not_sealed')
        return dict(status='fail' if failures else 'unknown' if unavailable else 'pass',
            checked=checked,failures=failures,unavailable=unavailable,function_counts=function_counts,
            exercised=checked>0,
            elapsed_seconds=time.perf_counter()-started,
            capture_overhead_seconds=status.get('capture_overhead_seconds'),provider_calls_added=0)
    finally:socket.socket=original

def main():
    p=argparse.ArgumentParser();p.add_argument('--trace',required=True);p.add_argument('--lane',required=True)
    p.add_argument('--policy-hash',required=True);p.add_argument('--runtime-sha',required=True)
    p.add_argument('--source-root',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    sys.path.insert(0,str(Path(a.source_root).resolve()))
    try:row=replay(a.trace,lane=a.lane,policy_hash=a.policy_hash,runtime_sha=a.runtime_sha)
    except Exception as exc:row=dict(status='fail',checked=0,failures=[dict(classification='strategy_conformance_failure',reason=str(exc))])
    Path(a.output).write_text(canonical(row)+'\n')
    print(canonical({k:v for k,v in row.items() if k!='failures'}))
    raise SystemExit(0 if row['status']=='pass' else 1)

if __name__=='__main__':main()
