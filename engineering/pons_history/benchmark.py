"""Local acquisition measurements over synthetic tapes; never a provider proof.

All paths are under --state, which must be a new disposable directory. Transport
is replaced at the existing RPC boundary and network_guard forbids market I/O.
The measured HTTP column counts generated RPC batches, not actual HTTP requests.
Use strace on this process for cumulative SQLite/WAL writes; file sizes below are
retained sizes, not cumulative writes. No production database is opened.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import resource
import time
from unittest.mock import patch

from engineering.pons_history.fixtures import Tape
from meme_machine.lanes.pons.pons_historical import Preparation, PLAN
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
from operational.tests import network_guard


class EmptyTape(Tape):
    def __init__(self, blocks):
        super().__init__(candidates=0)
        self.top=self.first+blocks-1
        self.blocks=blocks

    def header(self,n):
        h=super().header(n)
        h['timestamp']=hex(self.start_at+(n-self.first)*604800//(self.blocks-1))
        return h


def metrics(tape):
    return dict(logical_rpc_elements=tape.logical, generated_transport_batches=tape.physical,
        methods=dict(tape.methods), errors=dict(tape.failures),
        encoded_request_bytes=tape.request_bytes,encoded_response_bytes=tape.response_bytes,
        cache_hits=0,estimated_cu=tape.logical*100,actual_billed_cu=None)


def io_bytes():
    return {k:int(v) for k,v in (line.split(':') for line in Path('/proc/self/io').read_text().splitlines())}


def profile(action, tape, dbpath):
    before=metrics(tape);cpu=time.process_time();wall=time.monotonic();io=io_bytes()
    action()
    end=metrics(tape)
    result={k:(end[k]-before[k] if isinstance(end[k],int) else end[k]) for k in end}
    result['methods']=dict(Counter(end['methods'])-Counter(before['methods']))
    result.update(cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-wall,
        process_storage_write_bytes=io_bytes()['write_bytes']-io['write_bytes'],
        peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        retained_sqlite_bytes=dbpath.stat().st_size,
        retained_wal_bytes=Path(str(dbpath)+'-wal').stat().st_size)
    return result


def run(state, blocks):
    network_guard()
    state.mkdir(parents=True,exist_ok=False)
    results=[]
    with patch.dict(os.environ,dict(MM_DIRECTIONAL_SLEEVE_DB=str(state/'sleeve.sqlite'),
            MM_DIRECTIONAL_COHORT_ID='historical-offline-benchmark'),clear=True):
        for approach in ('legacy10','prepared10','prepared40_conditional'):
            tape=EmptyTape(blocks)
            root=state/approach
            r=Runtime(root,10**18,'offline','https://offline.invalid');r.rpc=tape
            r.now=lambda:int(tape.header(tape.top)['timestamp'],16)
            p=None
            try:
                if approach=='legacy10':
                    r.history.set_meta('discovery_block',tape.first-1)
                    r.history.set_meta('discovery_block_hash',tape.header(tape.first-1)['hash'])
                    def census():
                        while r.history.get_meta('discovery_block')<tape.top:
                            tape.provider();r.discover()
                else:
                    width=40 if approach.endswith('conditional') else 10
                    support=dict(schema='pons-log-range-comparison-v1',chain_id=4663,
                        provider_fingerprint=tape.provider_fingerprint,equal=True,range_blocks=40,
                        filter=Preparation.population_filter(),canonical_end_hash=tape.header(tape.top)['hash'],
                        baseline_digest='synthetic-offline-capability-only') if width==40 else None
                    p=Preparation(r.history,tape.provider,range_blocks=width,support=support)
                    def boundary():
                        p.begin()
                        while 'first' not in r.history.get_meta(PLAN):p.boundary_step()
                    initialization=profile(boundary,tape,root/'history.sqlite')
                    def census():
                        while (r.history.get_meta('pons_historical_frontier:population') or
                               dict(block=tape.first-1))['block']<tape.top:p.discover_step()
                measured=profile(census,tape,root/'history.sqlite')
                if p:
                    if not p.readiness()['ready']:raise AssertionError('synthetic census incomplete')
                    restoration=profile(p.resume,tape,root/'history.sqlite')
                else:restoration=None;initialization=None
                results.append(dict(approach=approach,blocks=blocks,
                    initial_boundary=initialization,population_discovery=measured,warm_restore=restoration,
                    candidate_count=0,scope='empty factory census; economic reconstruction excluded'))
            finally:r.close()
        # Same dense population and native pool reducer; transport costs for
        # mandatory receipts/senders are included in both paths, not patched away.
        for approach in ('legacy_economic','prepared_group_economic'):
            tape=Tape();root=state/approach
            r=Runtime(root,10**18,'offline','https://offline.invalid');r.rpc=tape
            p=Preparation(r.history,tape.provider,clock=r.now)
            try:
                p.begin()
                while 'first' not in r.history.get_meta(PLAN):p.boundary_step()
                while (r.history.get_meta('pons_historical_frontier:population') or dict(block=tape.first-1))['block']<tape.top:p.discover_step()
                while r.history.pending_graduations():p.authenticate_step()
                def transport(endpoint,calls,scope,**kwargs):
                    values=[]
                    for i in range(0,len(calls),50):
                        values.extend(tape.provider().batch(calls[i:i+50],scope=scope))
                    return values,[tape.telemetry()]
                def hydration():
                    while any(row['block']<tape.top for row in r.history.rows()):
                        if approach=='legacy_economic':
                            tape.provider();r._increment_candidates(r.history.rows(),tape.top)
                        else:p.history_group_step(r,r.history.rows())
                with patch('meme_machine.lanes.pons.pons_selective_v4._batched',side_effect=transport):
                    measured=profile(hydration,tape,root/'history.sqlite')
                vectors={row['id']:r.history.facts(row['id'],int(tape.header(tape.top)['timestamp'],16))
                         for row in r.history.rows()}
                if approach=='legacy_economic':reference=vectors
                elif reference!=vectors:raise AssertionError('economic history disagreement')
                results.append(dict(approach=approach,blocks=tape.top-tape.grad,
                    candidate_count=len(tape.tokens),mandatory_economic_acquisition=measured,
                    exact_native_history_equal=True,scope='synthetic dense two-pool history'))
            finally:r.close()
    return dict(schema='pons-history-offline-cost-v1',synthetic_inputs=True,
        actual_market_provider_calls=0,production_economic_mutation=False,
        python=__import__('sys').version,cpu_count=os.cpu_count(),results=results,
        limitations=['generated batches are not physical HTTP measurements',
            'local CPU/RSS/write_bytes measured on this Droplet without provider waiting',
            'empty census cannot predict actual graduation/activity density',
            'forty-block result uses synthetic support, not account capability',
            'encoded JSON bytes omit live transport headers and compression',
            '100 CU per element is a diagnostic estimate, not billed CU'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--blocks',type=int,default=4096)
    args=parser.parse_args()
    if not 169<=args.blocks<=20000:raise ValueError('benchmark_work_bound')
    result=run(args.state,args.blocks)
    args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(cases=len(result['results']),actual_market_provider_calls=0)))


if __name__=='__main__':main()
