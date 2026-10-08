"""Chronological production-runtime replay against the frozen full collector.

Synthetic RPC replies are deterministic offline inputs, never market evidence.
Both runtimes authenticate the same graduation, ingest the same transaction
tape, build the original price/buyer windows, and use real Quotes decoding.
"""
from copy import deepcopy
import argparse
import json
from math import isqrt
import os
from pathlib import Path
import time
from unittest.mock import patch

from engineering.pons_history.fixtures import checksum, encoded_event
from engineering.robinhood_scout.replay import reference_module, WireTape, ENDPOINT
from tests.test_robinhood_scout import ObservationTape
from meme_machine.lanes.pons.abi import calldata, decode_event, words
from meme_machine.lanes.pons.identity import load
from meme_machine.lanes.pons import pons_selective_v4 as optimized
from meme_machine.lanes.pons.pons_historical import MANAGER, SWAP
from meme_machine.lanes.pons.pons_natural_observation import MarketScout
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime, price_index
from meme_machine.lanes.pons.pons_quotes import V4_QUOTER
from meme_machine.lanes.pons.protocols import PoolKey
from meme_machine.runtime.robinhood.plane import Plane
from meme_machine.runtime.journal import digest
from meme_machine.runtime.cu import estimate


def usage_difference(before,after):
    methods={k:after['methods'].get(k,0)-before['methods'].get(k,0) for k in after['methods']
             if after['methods'].get(k,0)!=before['methods'].get(k,0)}
    return dict(physical_http_attempts=after['physical_http_requests']-before['physical_http_requests'],
        logical_rpc_elements=sum(methods.values()),response_bytes=after['response_bytes']-before['response_bytes'],
        methods=methods,diagnostic_cu=estimate(methods),verified_billed_cu=None)


class DecisionTape(ObservationTape):
    def __init__(self, *, quiet=False, concentration=False):
        self.times=None
        super().__init__(candidates=1)
        token=self.tokens[0];record=self.records[token]
        init=next(e for e in self.logs if e['topics'][0]==
            __import__('meme_machine.lanes.pons.pons_natural_paper',fromlist=['_event_topic'])._event_topic('uniswap_v4_manager','Initialize'))
        self.initial_sqrt=decode_event(load('uniswap_v4_manager')['abi'],init)['args']['sqrtPriceX96']
        self.grad_at=int(super().header(self.grad)['timestamp'],16)
        self.logs=[e for e in self.logs if int(e['blockNumber'],16)<=self.grad]
        self.key=PoolKey('0x'+'0'*40,token,record['poolFee'],record['tickSpacing'],load('pons_v2_hook')['address'].lower())
        # This path supplies a reset and base before the breakout. Each block
        # is only exposed when top advances; late observations cannot leak.
        points=[(1800,11000),(3600,12500),(7200,11200),(9000,11500),
            (12400,11600),(12401,11600),(12402,11600),(12600,11800),
            (13400,12000),(13401,12000),(13402,12000),(14100,13000),(14101,13000),(14400,13500)]
        if quiet:
            points=[(t,min(p,11800) if t>=13400 else p) for t,p in points]
            points += [(14800,11800),(14801,11800),(14802,11800),(16200,11800),
                (16400,12000),(16401,12000),(16402,12000),(17700,13000),(17701,13000),(18000,13500)]
        self.times={self.grad+i+1:t for i,(t,_) in enumerate(points)}
        self.sqrt_by_block={self.grad:self.initial_sqrt}
        for i,(at,p) in enumerate(points):
            block=self.grad+i+1;tx=checksum('decision:'+str(i));sqrt=isqrt(self.initial_sqrt**2*10000//p)
            self.sqrt_by_block[block]=sqrt
            sender=f'0x{1 if concentration else 100+i:040x}'
            self.senders[tx]=sender
            self.logs.append(encoded_event('uniswap_v4_manager','Swap',dict(id=self.key.pool_id(),
                sender='0x'+'ff'*20,amount0=10**18,amount1=-10**18,sqrtPriceX96=sqrt,
                liquidity=10**24,tick=0,fee=record['poolFee']),block=block,
                block_hash=self.header(block)['hash'],tx=tx,tx_index=i+4))
        self.top=self.grad

    def header(self,n):
        h=super().header(n)
        if self.times is not None:
            offset=self.times.get(n,(n-self.grad)*60 if n<=self.grad else max(self.times.values()))
            h['timestamp']=hex(self.grad_at+offset)
        return h

    def _read(self,method,params):
        if method=='eth_getCode' and params[0].lower()==V4_QUOTER.lower():return '0x6000'
        if method=='eth_gasPrice':return '0x1'
        if method=='eth_call':
            q=params[0]
            if q['to'].lower()==MANAGER:
                return '0x'+f'{self.sqrt_by_block[self.top]:064x}'
            if q['to'].lower()==V4_QUOTER.lower():
                if q['data']==calldata('poolManager()'):return '0x'+f'{int(MANAGER,16):064x}'
                values=words('0x'+q['data'][10:]);buy=int.from_bytes(values[6],'big')==1
                amount=int.from_bytes(values[7],'big')
                out=amount*100 if buy else amount*99//10000
                return '0x'+f'{out:064x}'+f'{200000:064x}'
        return super()._read(method,params)


def replay_case(root, *, quiet=False, concentration=False):
    tape=DecisionTape(quiet=quiet,concentration=concentration)
    full=reference_module('pons_survivor_runtime.py');collector=reference_module('pons_selective_v4.py')
    full.collect_v4_activity=collector.collect_v4_activity
    full.collect_v4_activities=collector.collect_v4_activities
    with patch.dict(os.environ,dict(MM_DIRECTIONAL_SLEEVE_DB=str(root/'sleeve.sqlite'),
        MM_DIRECTIONAL_COHORT_ID='decision-offline'),clear=True):
        plane=Plane(root/'plane.sqlite',clock=lambda:int(tape.header(tape.top)['timestamp'],16))
        scout=MarketScout(plane)
        new=Runtime(root/'optimized',10**18,'decision',ENDPOINT,scout_path=plane.path)
        old=full.Runtime(root/'reference',10**18,'decision-reference',ENDPOINT)
        try:
            for runtime in (old,new):
                runtime.rpc=tape;runtime.deployments_verified=True
                runtime.now=lambda:int(tape.header(tape.top)['timestamp'],16)
            scout.read_market(tape,tape.grad-10,tape.grad)
            nomination_usage=deepcopy(tape.telemetry())
            for _ in range(20):
                new.discover()
                if not new.history.pending_graduations():break
            token=tape.tokens[0];row=new.history.get(token)
            if not row:raise AssertionError('canonical_graduation_missing')
            authentication_usage=deepcopy(tape.telemetry())
            old.history.graduate(token,deepcopy(row['graduation']))
            anchor=price_index(tape.initial_sqrt,token,tape.key)
            old.history.append_block(token,block=tape.grad,header=tape.header(tape.grad),
                events=[],points=[(row['graduation']['at'],str(anchor))])
            old.history_ready=True # complete reference census; compare individual economics
            outcomes=[]
            ends=[tape.grad+14,tape.grad+24] if quiet else [tape.grad+14]
            for end in ends:
                tape.top=end
                scout.read_market(tape,plane.checkpoint_read('pons_scout_market_cursor')+1,end)
                scout.read_pools(tape,end)
                decisions=[];facts=[];quote_counts=[];qualification_work=[]
                for runtime,module in ((old,collector),(new,optimized)):
                    wire=WireTape(tape)
                    with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=wire.response), \
                         patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',side_effect=wire.session):
                        runtime._increment(runtime.history.get(token),end)
                    state=runtime.fresh_state(token);quotes=runtime.fresh_quotes(state,5*10**16)
                    before_quote=deepcopy(tape.telemetry())
                    acquired=runtime.reconstruct(state,quotes);decision=runtime.qualify(acquired)
                    after_quote=tape.telemetry()
                    methods={k:after_quote['methods'].get(k,0)-before_quote['methods'].get(k,0)
                        for k in after_quote['methods'] if after_quote['methods'].get(k,0)!=before_quote['methods'].get(k,0)}
                    qualification_work.append(dict(methods=methods,diagnostic_cu=estimate(methods),
                        physical_http_attempts=after_quote['physical_http_requests']-before_quote['physical_http_requests'],
                        response_bytes=after_quote['response_bytes']-before_quote['response_bytes']))
                    decisions.append(decision);facts.append(acquired);quote_counts.append(len(quotes.cache))
                # Weak candidates deliberately leave execution UNKNOWN. Compare
                # every nonexecution feature and the complete eligible decisions.
                ignored={'roundtrip_loss_bps','double_size_roundtrip_loss_bps'}
                economic=[{k:v for k,v in d['features'].items() if k not in ignored} for d in decisions]
                if economic[0]!=economic[1] or decisions[0]['candidate']!=decisions[1]['candidate']:
                    raise AssertionError(dict(economic= economic,decisions=decisions))
                if decisions[1]['candidate'] and decisions[0]!=decisions[1]:
                    raise AssertionError('complete_eligible_decision_difference')
                before,after=[runtime.history.facts(token,new.now()) for runtime in (old,new)]
                if before!=after:raise AssertionError('transaction_buyer_or_price_history_difference')
                outcomes.append(dict(at=new.now(),age_seconds=new.now()-row['graduation']['at'],
                    candidate=decisions[1]['candidate'],features_digest=digest(economic[1]),
                    authenticated_tapes_equal=True,complete_eligible_decisions_equal=True,
                    reference_quote_sizes=quote_counts[0],optimized_quote_sizes=quote_counts[1],
                    original_deadline=row['graduation']['at']+7*86400,
                    optimized_execution_status=facts[1]['execution_evidence_status'],
                    reference_quote_work=qualification_work[0],optimized_quote_work=qualification_work[1],
                    missing_execution_is_economic_rejection=False))
            if quiet and [r['candidate'] for r in outcomes] != [False,True]:
                raise AssertionError(outcomes)
            if not quiet and not concentration and not outcomes[0]['candidate']:raise AssertionError(decisions)
            if concentration and outcomes[0]['candidate']:raise AssertionError('concentration_gate_lost')
            positions_equal=None;capital_recovery=None;position_quote_usage=None;position_turn_usage=None
            if outcomes[-1]['candidate']:
                new.sleeve.reserve('competing-capital',strategy='pons-selective-continuation-v1',
                    amount=10**18,at=new.now()-1,asset='another-asset')
                old.discover=lambda:None # reference population is already complete
                # Run actual orchestrators and durable accounting, then retry the
                # same economic winner after capital returns. Current outcome
                # and unavailable cash never remove Survivor qualification.
                results=[]
                for runtime in (old,new):
                    runtime._provider=lambda:tape.provider()
                    result=runtime.step(admit=True);r=runtime.history.get(token)
                    if not r.get('decision',{}).get('candidate') or runtime.book.reconcile()['open_positions']:
                        raise AssertionError(dict(row=r,result=result))
                    results.append(r['decision'])
                if results[0]!=results[1]:raise AssertionError('capital_denial_decision_difference')
                new.sleeve.release('competing-capital',pnl=0,at=new.now(),cancelled=True,
                    native_verified=True,terminal_hash=digest('offline-capital-return'))
                # Independent runtimes deliberately share the canonical sleeve;
                # opening both would contend on one asset reservation. Exercise
                # the optimized native commit, then idempotent repeat discovery.
                r=new.history.get(token);r['scout_next_check']=new.now();new.history.save(r)
                result=new.step(admit=True);r=new.history.get(token)
                if not r.get('position') or new.book.reconcile()['open_positions']!=1:
                    raise AssertionError(dict(row=r,result=result))
                capital_recovery=True
                before=tape.telemetry();new.current=r
                with patch('time.time',return_value=new.now()):
                    q=new.exit_quote(new.book._load(r['position'])['tokens'])
                after=tape.telemetry()
                if q is None:raise AssertionError('position_quote_lost')
                methods={k:after['methods'].get(k,0)-before['methods'].get(k,0) for k in after['methods']
                    if after['methods'].get(k,0)!=before['methods'].get(k,0)}
                position_quote_usage=dict(physical_http_attempts=after['physical_http_requests']-before['physical_http_requests'],
                    response_bytes=after['response_bytes']-before['response_bytes'],methods=methods,
                    diagnostic_cu=estimate(methods),cadence_changed=False)
                # Native quote paths must have identical authentic execution.
                old.current=old.history.get(token)
                with patch('time.time',return_value=old.now()):
                    oq=old.exit_quote(new.book._load(r['position'])['tokens'])
                if {k:v for k,v in q.items() if k!='acquired'}!={k:v for k,v in oq.items() if k!='acquired'}:
                    raise AssertionError('position_quote_economics_difference')
                positions_equal=True
                before=tape.telemetry()
                with patch('time.time',return_value=new.now()):new.step(admit=False)
                position_turn_usage=usage_difference(before,tape.telemetry())
                position_turn_usage['scope']='native funded step, unchanged head with no economic delta; excludes new swaps and conditional exit/scaling work'
                if new.book.reconcile()['open_positions']>1:raise AssertionError('duplicate_position')
            storage={}
            for name,db in (('shared_plane',plane.db),('optimized_history',new.history.db),('reference_history',old.history.db)):
                pages=db.execute('PRAGMA page_count').fetchone()[0];size=db.execute('PRAGMA page_size').fetchone()[0]
                storage[name]=dict(sqlite_page_stock_bytes=pages*size,
                    free_pages=db.execute('PRAGMA freelist_count').fetchone()[0],
                    interpretation='offline logical SQLite page stock; not cumulative disk writes, WAL stock or a monthly projection')
            return dict(case='quiet_then_breakout' if quiet else 'concentrated_buyer_rejection' if concentration else 'accelerating_buyers',
                candidate_recall=1.0,points=outcomes,lookahead=False,reference_source_sha256=full.source_sha256,
                capital_denial_then_native_open=capital_recovery,position_quotes_equal=positions_equal,
                position_quote_usage=position_quote_usage,
                position_turn_usage=position_turn_usage,storage=storage,
                nomination_usage=nomination_usage,nomination_plus_authentication_usage=authentication_usage)
        finally:old.close();new.close();plane.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Scratch
    network_guard()
    with Scratch() as scratch:
        rows=[]
        for i,kwargs in enumerate(({},dict(quiet=True),dict(concentration=True))):
            root=scratch.path/str(i);root.mkdir();rows.append(replay_case(root,**kwargs));scratch.check()
        args.output.write_text(json.dumps(dict(schema='robinhood-native-decision-replay-v1',cases=rows,
            evidence_basis='synthetic canonical-shaped chronological RPC tape; real production reducers and Quotes',
            production_deadline_certification='NOT_MEASURED'),indent=2)+'\n')
        scratch.success=True


if __name__=='__main__':main()
