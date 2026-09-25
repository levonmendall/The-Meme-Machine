"""Exact-call offline Ramses replay from run 364's preserved initial scan."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from .plane import canonical


class RecordedRpc:
    # Only preserved authenticated responses; external I/O is unconditionally blocked.
    canonical_authority=True
    chain_verified=True
    provider_fingerprint="retained-run364-alchemy"
    def __init__(self,fixture):
        self.frontier=fixture['frontier'];self.responses={};self.calls=[];self.origins={}
        for transport in fixture['transports']:
            for row in transport['reads']:
                key=self.key(row['method'],row['params'])
                old=self.responses.get(key)
                if old is not None and old!=row['response']:raise ValueError('retained_exact_state_conflict')
                self.responses[key]=row['response']
                self.origins.setdefault(key,set()).add(transport['physical_request_id'])
    def key(self,method,params):
        params=json.loads(json.dumps(params))
        if isinstance(params[0],dict) and 'to' in params[0]:params[0]['to']=params[0]['to'].lower()
        elif method=='eth_getCode':params[0]=params[0].lower()
        if params[-1]==self.frontier['number']:params[-1]={'blockHash':self.frontier['hash']}
        return canonical([method,params])
    def call(self,method,params,scope=None):
        key=self.key(method,params)
        if key not in self.responses:raise ValueError('UNMEASURABLE_missing_exact_retained_call:'+key)
        self.calls.append(key);return self.responses[key]
    def batch(self,calls,scope=None):return [self.call(m,p,scope) for m,p in calls]


def run(fixture,lane,output):
    attempts=[]
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo'):
            attempts.append(event);raise RuntimeError('offline_network_forbidden')
    sys.addaudithook(guard);sys.path.insert(0,str(Path(lane).resolve()))
    from robinhood_research.ramses_universe import _prestate
    from robinhood_research.ramses_costs import quote_native_cycle,CATEGORIES
    from robinhood_research.ramses_strategy import classify_pool,pool_features,wide_range_capital_ceiling,POLICY_HASH
    from .ramses import RouteIndex
    raw=Path(fixture).read_bytes();data=json.loads(gzip.decompress(raw));screen=data['screen'];block=screen['finalized_block']
    factory=screen['factory']['address'];oldrpc=RecordedRpc(data);newrpc=RecordedRpc(data)
    old=[];new=[];newfeatures=[];route_results=[]
    # The recorded scan inherited the already-authenticated immutable router
    # WNATIVE identity. Preserve that exact retained cost-state input.
    seed={'wnative':screen['rows'][0]['cost_evidence']['conversion']['wnative']}
    route_state_old=dict(seed);route_state_new=dict(seed)
    with tempfile.TemporaryDirectory() as tmp:
        index=RouteIndex(Path(tmp)/'replay.sqlite',POLICY_HASH,source='retained-run364-alchemy')
        for row in screen['rows']:
            auth=dict(token_x=row['token_x'],token_y=row['token_y'],bin_step=row['prestate']['step'])
            _,full=_prestate(oldrpc,factory,row['pool'],block,bin_radius=100,authenticated_pool=auth)
            retained=dict(row['prestate'],bins={int(k):v for k,v in row['prestate']['bins'].items()})
            assert full==retained,'retained_full_state_divergence'
            meta=row['cost_evidence'];native={k:meta['gas_units'][k]*meta['gas_price_native_raw'] for k in (*CATEGORIES,'entry_overhead')}
            costs,conversion=quote_native_cycle(oldrpc,factory,row,block,native,route_state_old)
            assert costs==row['gas_costs'],'retained_cost_divergence'
            cheap={k:row[k] for k in ('pool','token_x','token_y','quote_side')}
            index.begin(factory,cheap,data['frontier'],{'native_costs':native})
            capability=index.check(newrpc,factory,cheap,data['frontier'],native,route_state_new)
            assert capability['costs']==costs and capability['meta']==conversion,'preflight_cost_divergence'
            radius=1 if capability['skip_deep'] else 100
            _,state=_prestate(newrpc,factory,row['pool'],block,bin_radius=radius,authenticated_pool=auth)
            feature=pool_features(state,row['prehistory'],row['quote_side'],pool=row['pool'])
            assert feature==pool_features(full,row['prehistory'],row['quote_side'],pool=row['pool']),'percentile_input_divergence'
            newfeatures.append(feature);old.append((row,full,costs));new.append((row,state,costs,capability))
            route_results.append(dict(pool=row['pool'],route_incapable=capability['skip_deep'],old_bin_radius=100,new_bin_radius=radius))
        comparisons=[]
        for (row,full,costs),(_,state,_,capability) in zip(old,new):
            def decide(prestate):
                return classify_pool(prestate,row['prehistory'],row['quote_side'],
                    requested_capital=max(1,wide_range_capital_ceiling(prestate,row['quote_side'])),
                    entry_timestamp=screen['finalized_timestamp'],gas_costs=costs,
                    universe_features=newfeatures,now=screen['finalized_timestamp'],
                    pool=row['pool'],quote_token=row['quote_token'])
            baseline=decide(full)
            if capability['skip_deep']:
                assert not baseline['qualified'],'route_veto_changed_qualification'
                comparisons.append(dict(pool=row['pool'],complete_equivalent_evidence=False,
                    qualification_preserved=True,baseline_reasons=baseline['reasons'],
                    preflight_reason=capability['meta']['reason']))
            else:
                current=decide(state);assert current==baseline,'frozen_decision_divergence'
                comparisons.append(dict(pool=row['pool'],complete_equivalent_evidence=True,
                    inputs_equal=state==full,decision_equal=True,reason_equal=True,economics_equal=True))
            index.complete(row['pool'],{'decision':baseline})
        index.close()
    avoided=set(oldrpc.calls)-set(newrpc.calls)
    affected=set().union(*(oldrpc.origins[k] for k in avoided)) if avoided else set()
    report=dict(passed=not attempts,run=364,scope='two retained initial-scan pools; current frozen v4 applied to identical retained evidence',
        historical_policy=screen['policy_hash'],current_policy=POLICY_HASH,fixture_sha256=hashlib.sha256(raw).hexdigest(),
        pools=route_results,behavioral_equivalence=comparisons,
        old_logical_reads=len(oldrpc.calls),new_logical_reads=len(newrpc.calls),avoided_logical_reads=len(oldrpc.calls)-len(newrpc.calls),
        deep_hydrations_avoided=sum(r['route_incapable'] for r in route_results),
        historical_transports_containing_avoided_reads=len(affected),new_physical_transports='UNMEASURABLE',
        physical_limitation='Reordered batches and cache hits cannot be assigned original transport timings or physical grouping.',
        provider_calls=0,network_attempts=len(attempts),profitability_claim=False)
    Path(output).write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps(report,sort_keys=True))
    return 0


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fixture',required=True);p.add_argument('--ramses',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();raise SystemExit(run(a.fixture,a.ramses,a.output))
