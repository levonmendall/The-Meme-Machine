"""Separately reviewed, single forty-block filter comparison; default is offline.

Never run under the 300-second plan: its ten-block ceiling is unchanged. This
proposed comparison needs its own owner authorization for the exact filter and
nonempty interval. It cannot clear the combined position/candidate latency guard.
"""
import argparse
import json
import os
from pathlib import Path

from . import proof
from meme_machine.lanes.pons.log_windows import filter_profile,LogWindows
from meme_machine.runtime.journal import digest


class RangeBudget(proof.Budget):
    def __init__(self):
        super().__init__()
        self.plan.update(maximum_elapsed_seconds=45,maximum_total_physical_http_attempts=32,
            maximum_public_physical_http_attempts=0,maximum_alchemy_physical_http_attempts=32,
            maximum_total_logical_rpc_elements=64,maximum_alchemy_logical_rpc_elements=64,
            maximum_getLogs_blocks_per_element=40,maximum_diagnostic_estimated_alchemy_cu=6400,
            maximum_http_response_bytes=64*1024*1024,maximum_temporary_artifact_bytes=128*1024*1024)


def validate(query):
    from meme_machine.lanes.pons.pons_historical import FACTORY,LAUNCH,GRADUATION,MANAGER,ACTIVITY
    from meme_machine.lanes.pons.abi import topic
    curve=[topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)'),
           topic('CurveSell(address,address,uint256,uint256,uint256,uint256)')]
    static,counts=filter_profile(query)
    if set(query)-{'topics','address'}:raise ValueError('capability_static_filter_required')
    if 'address' not in query:
        valid=len(query['topics'])==1 and static['topics0']==sorted([LAUNCH,GRADUATION,*curve])
    elif query['address']==FACTORY:
        valid=len(query['topics'])==1 and static['topics0']==sorted([LAUNCH,GRADUATION])
    elif query['address']==MANAGER:
        valid=len(query['topics'])==2 and set(static['topics0'])<=set(ACTIVITY) and 1<=counts[0]<=64
    else:valid=False
    if not valid:raise ValueError('capability_strategy_filter_required')
    return query


def compare(out,budget,*,query,first,app_id='v5h0vqr0wpp9zscj',team_id=None):
    """Acquire/authenticate exact ten-block union and compare the wider array."""
    import os
    from meme_machine.lanes.pons.provider_topology import configured_rpc
    from meme_machine.runtime.robinhood.provider_authority import fingerprint
    from meme_machine.lanes.pons.identity import load,authenticate
    from meme_machine.lanes.pons.pons_historical import FACTORY,MANAGER
    from meme_machine.lanes.pons import BoundaryError
    query=validate(query)
    if type(first) is not int or first<1:raise ValueError('capability_interval_required')
    last=first+39;endpoint=os.environ['MM_ROBINHOOD_READ_RPC_URL']
    rpc=configured_rpc(endpoint,limit=64,per_scope=64,retries=0)
    def reads(calls):return rpc.batch(calls,scope='pons_payg_capability')
    rpc.verify_chain()
    role='uniswap_v4_manager' if query.get('address')==MANAGER else 'pons_v2_factory'
    address=load(role)['address'].lower()
    code=reads([('eth_getCode',[address,hex(first)])])[0];authenticate(role,address,code)
    numbers=[0,first-1,first,last]
    before=reads([('eth_getBlockByNumber',[hex(n),False]) for n in numbers])
    if any(int(h['number'],16)!=n for n,h in zip(numbers,before)) or before[2]['parentHash']!=before[1]['hash']:
        raise BoundaryError('capability_boundary_identity')
    pages=reads([('eth_getLogs',[dict(query,fromBlock=hex(n),toBlock=hex(n+9))]) for n in range(first,last+1,10)])
    validator=LogWindows(endpoint,query);baseline=[]
    for n,page in zip(range(first,last+1,10),pages):baseline.extend(validator._validate(page,n,n+9))
    if not baseline:raise BoundaryError('capability_nonempty_sample_required')
    # These receipts prove exact canonical transaction membership. The runtime
    # still performs full ABI, token/curve/pool lineage and economic validation.
    pairs=list(dict.fromkeys((e['transactionHash'],e['blockHash']) for e in baseline))
    headers={}
    blocks=list(dict.fromkeys((int(e['blockNumber'],16),e['blockHash']) for e in baseline))
    for at in range(0,len(blocks),50):
        group=blocks[at:at+50]
        values=reads([('eth_getBlockByNumber',[hex(n),False]) for n,_ in group])
        if any(h.get('hash')!=bh or int(h['number'],16)!=n for (n,bh),h in zip(group,values)):
            raise BoundaryError('capability_header_canonical_membership')
        headers.update((bh,h) for (_,bh),h in zip(group,values))
    for at in range(0,len(pairs),50):
        group=pairs[at:at+50]
        receipts=reads([('eth_getTransactionReceipt',[tx]) for tx,_ in group])
        for (tx,bh),receipt in zip(group,receipts):
            if receipt.get('transactionHash')!=tx or receipt.get('blockHash')!=bh or receipt.get('status')!='0x1':
                raise BoundaryError('capability_receipt_identity')
            h=headers[bh]
            if h.get('hash')!=bh:raise BoundaryError('capability_header_identity')
            for event in (e for e in baseline if e['transactionHash']==tx):
                if event not in receipt['logs'] or int(h['number'],16)!=int(event['blockNumber'],16):
                    raise BoundaryError('capability_receipt_membership')
    larger=reads([('eth_getLogs',[dict(query,fromBlock=hex(first),toBlock=hex(last))])])[0]
    candidate=validator._validate(larger,first,last)
    if baseline!=candidate:raise BoundaryError('capability_exact_union_disagreement')
    after=reads([('eth_getBlockByNumber',[hex(n),False]) for n in numbers])
    if before!=after:raise BoundaryError('capability_range_reorganization')
    budget.time_check();static,counts=filter_profile(query)
    row=dict(schema='pons-log-window-capability-v1',provider_fingerprint=fingerprint(endpoint),chain_id=4663,
        app_id=app_id,team_id=team_id,entitlement_status='VERIFIED',filter=static,indexed_filter_counts=counts,
        range_blocks=40,first=first,last=last,equal=True,event_count=len(baseline),
        baseline_digest=digest(baseline),candidate_digest=digest(candidate),canonical_end_hash=after[-1]['hash'],
        usage=budget.snapshot(),scope='this nonempty endpoint/filter/cardinality sample; not larger or denser intervals')
    (out/'comparison.json').write_text(json.dumps(dict(comparisons=[row]),indent=2)+'\n')
    return dict(status='SUPPORTED_40_BLOCK_SAMPLE',comparison=row,guard_removed=False,provider_certified=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--source-commit')
    parser.add_argument('--env-file',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--filter-file',type=Path);parser.add_argument('--first',type=int);parser.add_argument('--team-id')
    args=parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(dict(status='NOT_RUN',authorization='SEPARATE_OWNER_REVIEW_REQUIRED',
            proposed_limits=RangeBudget().plan,filter_and_nonempty_interval_required=True),indent=2));return 0
    source=proof.identity()
    if (os.environ.get('CI') or source['dirty'] or args.source_commit!=source['commit'] or not args.env_file or not args.output
            or not args.filter_file or not args.first or not args.team_id):
        parser.error('exact clean source, protected env, output, exact filter/interval and team ID required')
    query=validate(json.loads(args.filter_file.read_text()));out=args.output.absolute()
    if out.exists() or out.resolve()!=out or str(out).startswith('/mnt/'):
        parser.error('new isolated root-disk output required')
    from meme_machine.operational.artifact_storage import Scratch
    with Scratch() as scratch:
        scratch.check();out.mkdir(mode=0o700,parents=True)
        result=proof.supervise(out,proof.environment(args.env_file),budget_factory=RangeBudget,
            action=lambda root,budget:compare(root,budget,query=query,first=args.first,team_id=args.team_id))
        scratch.check();scratch.success=result['status']!='FAIL'
    print(json.dumps(dict(status=result['status'],result=str(out/'result.json'),reason=result.get('reason'))))
    return 0 if result['status']=='SUPPORTED_40_BLOCK_SAMPLE' else 2


if __name__=='__main__':raise SystemExit(main())
