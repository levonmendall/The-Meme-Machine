"""Reproducible offline wire comparison, including the last published scout.

Synthetic canonical-shaped events exercise real collectors and RPC encoding.
The paid capability file exists only inside Scratch and proves no live endpoint.
"""
import argparse
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import time
import types
from unittest.mock import patch

from engineering.pons_history.fixtures import Tape
from engineering.robinhood_scout.replay import WireTape, markets, ENDPOINT
from meme_machine.lanes.pons import abi, pons_selective_v4 as current
from meme_machine.lanes.pons.log_windows import LogWindows,filter_profile
from meme_machine.runtime.journal import digest
from meme_machine.runtime.robinhood.provider_authority import fingerprint

ORIGINAL='b1f215edd3dc079b623401c7e09e9c91a380e6a0'
SCOUT='842c99c462f42dda582d9211b16242ae12dff225'


def module_at(ref):
    content=subprocess.check_output(['git','show',ref+':meme_machine/lanes/pons/pons_selective_v4.py'],text=True)
    module=types.ModuleType('meme_machine.lanes.pons._payg_reference_'+ref[:8])
    module.__package__='meme_machine.lanes.pons'
    exec(compile(content,'git:'+ref, 'exec'),module.__dict__)
    return module,hashlib.sha256(content.encode()).hexdigest()


def fixture_capability(path,query):
    static,counts=filter_profile(query)
    row=dict(schema='pons-log-window-capability-v1',provider_fingerprint=fingerprint(ENDPOINT),
        chain_id=4663,app_id='SYNTHETIC_OFFLINE_APP',team_id='SYNTHETIC_OFFLINE_TEAM',
        entitlement_status='VERIFIED',filter=static,indexed_filter_counts=counts,range_blocks=40,
        equal=True,event_count=1,canonical_end_hash='synthetic-canonical-comparison',
        baseline_digest=digest('synthetic-nonempty-comparison'),synthetic=True)
    path.write_text(json.dumps(dict(comparisons=[row])))


def collect(module,tape,blocks,*,cap=None,original=False):
    selected=[dict(m,pool_id=m['key'].pool_id()) for m in markets(tape)]
    wire=WireTape(tape);cpu=time.process_time();wall=time.monotonic()
    cache=patch.object(abi,'topic',abi.topic.__wrapped__) if original else nullcontext()
    with cache,patch.dict('os.environ',{'MM_PONS_LOG_CAPABILITY_FILE':str(cap) if cap else ''}), \
         patch('meme_machine.lanes.pons.provider.urlopen',side_effect=wire.response), \
         patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',side_effect=wire.session):
        outputs=module.collect_v4_activities(ENDPOINT,markets=selected,
            start_block=tape.grad+1,end_block=tape.grad+blocks)
    stats=wire.snapshot();stats.update(cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-wall)
    for result in outputs.values():result.pop('provider_sessions',None)
    return outputs,stats


def comparison(root,candidates,blocks):
    tape=Tape(candidates=candidates);receipt=tape.receipt_value
    tape.receipt_value=lambda tx:dict(receipt(tx),**{'from':tape.senders.get(tx,'0x'+'01'*20)})
    original,original_hash=module_at(ORIGINAL);scout,scout_hash=module_at(SCOUT)
    query=current.acquisition_windows(ENDPOINT,[m['key'].pool_id() for m in markets(tape)]).query
    cap=root/'capability.json';fixture_capability(cap,query)
    outcomes=[];measurements={}
    for name,module,options in [('original',original,dict(original=True)),('published_scout',scout,{}),
            ('optimized_default_ten',current,{}),('optimized_fixture_paid_forty',current,dict(cap=cap))]:
        outcome,stats=collect(module,tape,blocks,**options);outcomes.append(outcome);measurements[name]=stats
    if any(row!=outcomes[0] for row in outcomes):raise AssertionError('complete_economic_tape_difference')
    return dict(candidates=candidates,blocks=blocks,canonical_normalized_tapes_equal=True,
        candidate_recall=1.,digest=digest(outcomes[0]),measurements=measurements,
        original_reference=ORIGINAL,original_source_sha256=original_hash,
        scout_reference=SCOUT,scout_source_sha256=scout_hash,
        measurement_basis='synthetic events; real production collector and HTTP boundary',
        fixture_paid_capability_is_live_verified=False,verified_billed_cu=None,network_latency=None)


def range_case(root,*,name,blocks,density):
    query=current.acquisition_windows(ENDPOINT,['0x'+'12'*32]).query
    cap=root/'range-capability.json';fixture_capability(cap,query)
    outcomes=[];stats={}
    for label,path in [('ten',root/'absent'),('fixture_forty',cap)]:
        wire=WireTape(Tape(candidates=0))
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=wire.response):rpc=wire.session()
        def response(request,**kwargs):
            values=json.loads(request.data);batch=isinstance(values,list);replies=[]
            for q in values if batch else [values]:
                f,l=(int(q['params'][0][k],16) for k in ('fromBlock','toBlock'))
                rows=[dict(address=query['address'],topics=[query['topics'][0],query['topics'][1][0]],
                    blockNumber=hex(b),blockHash='0x'+f'{b:064x}',transactionIndex=hex(i),
                    transactionHash='0x'+f'{b*10000+i:064x}',logIndex=hex(i),data='0x',removed=False)
                    for b in range(f,l+1) for i in range(density)]
                replies.append(dict(jsonrpc='2.0',id=q['id'],result=rows))
            import io
            return io.BytesIO(json.dumps(replies if batch else replies[0]).encode())
        planner=LogWindows(ENDPOINT,query,capability_path=path)
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=response):
            outcomes.append(planner.read(1,blocks,lambda calls:rpc.batch(calls,scope='offline_recovery')))
        stats[label]=dict(wire.snapshot(),planner=planner.telemetry())
    if outcomes[0]!=outcomes[1]:raise AssertionError('recovery_identity_difference')
    return dict(scenario=name,blocks=blocks,events=len(outcomes[0]),identity_equal=True,
        measurements=stats,fixture_only=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Scratch
    network_guard()
    with Scratch() as scratch:
        rows=[]
        for n,b in [(8,20),(32,40),(64,40)]:
            rows.append(comparison(scratch.path,n,b));scratch.check()
        ranges=[range_case(scratch.path,name=n,blocks=b,density=d) for n,b,d in
            [('quiet_recovery',160,0),('normal_recovery',160,1),('dense_interval',40,30)]]
        args.output.write_text(json.dumps(dict(schema='robinhood-payg-offline-efficiency-v1',
            cohorts=rows,ranges=ranges,live_provider_requests=0),indent=2)+'\n')
        scratch.check();scratch.success=True
    return 0


if __name__=='__main__':raise SystemExit(main())
