"""Run production collectors against one deterministic tape and the Git reference.

No provider workload is possible here: urlopen is replaced with an in-memory
JSON-RPC response, and the operational network guard forbids external sockets.
HTTP payload bytes/attempts are measured at the real Rpc HTTP code boundary,
but are explicitly an offline model, not measured network latency or billing.
"""
import argparse
from collections import Counter
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict
import hashlib
import io
import json
from math import isqrt
from pathlib import Path
import resource
import subprocess
import time
import types
from unittest.mock import patch

from engineering.pons_history.fixtures import Tape, encoded_event, checksum
from meme_machine.lanes.pons import pons_selective_v4 as optimized
from meme_machine.lanes.pons.identity import load
from meme_machine.lanes.pons.protocols import PoolKey
from meme_machine.lanes.pons.provider import Rpc
from meme_machine.runtime.cu import estimate
from meme_machine.runtime.journal import digest

REFERENCE='b1f215edd3dc079b623401c7e09e9c91a380e6a0'
ENDPOINT='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_SCOUT_REPLAY'


def reference_module(filename):
    content=subprocess.run(['git','show',REFERENCE+':meme_machine/lanes/pons/'+filename],
        check=True,capture_output=True,text=True).stdout
    module=types.ModuleType('meme_machine.lanes.pons._full_reference_'+filename[:-3])
    module.__package__='meme_machine.lanes.pons'
    module.__file__='git:'+REFERENCE+':'+filename
    exec(compile(content,module.__file__,'exec'),module.__dict__)
    module.source_sha256=hashlib.sha256(content.encode()).hexdigest()
    return module


class WireTape:
    def __init__(self,tape):self.tape=tape;self.sessions=[]

    def session(self,*args,**kwargs):
        rpc=Rpc(ENDPOINT,limit=200,per_scope=190,retries=0)
        rpc.canonical_authority=True;rpc.chain_verified=True
        rpc.provider_fingerprint='offline-comparison';rpc.evidence_deadline=kwargs.get('evidence_deadline')
        rpc.verify_chain();self.sessions.append(rpc)
        return rpc

    def response(self,request,**kwargs):
        values=json.loads(request.data);batch=isinstance(values,list)
        replies=[dict(jsonrpc='2.0',id=q['id'],result=self.tape._read(q['method'],q['params']))
            for q in (values if batch else [values])]
        return io.BytesIO(json.dumps(replies if batch else replies[0]).encode())

    def snapshot(self):
        values=[r.telemetry() for r in self.sessions]
        methods=Counter()
        for value in values:methods.update(value['methods'])
        return dict(physical_http_attempts=sum(v['physical_http_requests'] for v in values),
            logical_rpc_elements=sum(sum(v['methods'].values()) for v in values),methods=dict(methods),
            request_bytes=sum(v['request_bytes'] for v in values),response_bytes=sum(v['response_bytes'] for v in values),
            diagnostic_cu=estimate(methods),verified_billed_cu=None,cache_hits='not modeled in this HTTP comparison')


def markets(tape):
    return [dict(token=token,key=PoolKey(*sorted((r['token'],r['pairToken']),key=lambda x:int(x,16)),
        r['poolFee'],r['tickSpacing'],load('pons_v2_hook')['address'].lower()))
        for token,r in tape.records.items()]


def collect(module,tape,*,count=None,blocks=20):
    selected=markets(tape)[:count]
    selected=[dict(m,pool_id=m['key'].pool_id()) for m in selected]
    wire=WireTape(tape);cpu=time.process_time();wall=time.monotonic()
    from meme_machine.lanes.pons import abi
    # The reference decoder hashed every immutable ABI signature per event.
    # Restore that CPU behavior while leaving exact decoded values identical.
    uncached=(patch.object(abi,'topic',abi.topic.__wrapped__)
        if module.__file__.startswith('git:') else nullcontext())
    with uncached, patch('meme_machine.lanes.pons.provider.urlopen',side_effect=wire.response), \
         patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',side_effect=wire.session):
        outputs=module.collect_v4_activities(ENDPOINT,markets=selected,
            start_block=tape.grad+1,end_block=tape.grad+blocks)
    stats=wire.snapshot();stats.update(cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-wall)
    stats['maximum_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    for result in outputs.values():result.pop('provider_sessions',None)
    return outputs,stats


def compare(*,candidates=8,blocks=20):
    tape=Tape(candidates=candidates)
    # Standard RPC receipts include sender; use the transaction sender from the
    # same offline tape, never infer buyer independence from Swap.sender.
    original=tape.receipt_value
    def receipt(tx):return dict(original(tx),**{'from':tape.senders.get(tx,'0x'+'01'*20)})
    tape.receipt_value=receipt
    reference=reference_module('pons_selective_v4.py')
    before,baseline=collect(reference,tape,blocks=blocks)
    after,scout=collect(optimized,tape,blocks=blocks)
    if before!=after:raise AssertionError('canonical_collector_outcome_difference')
    return dict(reference=REFERENCE,reference_source_sha256=reference.source_sha256,
        candidates=candidates,blocks=blocks,canonical_normalized_tapes_equal=True,
        candidate_recall=len(after)/len(before),evidence_digest=digest(after),
        baseline=baseline,optimized=scout,
        physical_savings=baseline['physical_http_attempts']-scout['physical_http_attempts'],
        response_byte_savings=baseline['response_bytes']-scout['response_bytes'],
        diagnostic_cu_savings=baseline['diagnostic_cu']['known_estimated_cu']-scout['diagnostic_cu']['known_estimated_cu'],
        measurement_basis='real production Rpc code, in-memory HTTP replies; synthetic complete event tape',
        provider_latency='UNMEASURED',billing='UNMEASURED',production_capacity='NOT_CERTIFIED')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Scratch
    network_guard()
    with Scratch() as scratch:
        rows=[]
        for name,candidates,blocks in [('normal',8,20),('busy_market',32,40),('stress',64,40)]:
            scratch.check();row=compare(candidates=candidates,blocks=blocks);row['scenario']=name;rows.append(row)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(dict(schema='robinhood-scout-offline-comparison-v1',scenarios=rows),indent=2)+'\n')
        scratch.check();scratch.success=True


if __name__=='__main__':main()
