"""Small saved-workload comparison. Offline fixtures, no market or PAPER state."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import types
from unittest.mock import patch

from operational.tests import network_guard
from meme_machine.operational.artifact_storage import Scratch
from tests.test_solana_closure import state_at,NOW
from meme_machine.solana_evidence_plane import IntervalProof,digest
from meme_machine.solana_rolling_history import program_scope
from meme_machine.lanes.pump import solana_immutable_rpc as solana
from meme_machine.lanes.pump.provider import RPC
from meme_machine.lanes.pons import immutable_rpc as pons
from meme_machine.lanes.pons.provider_topology import PacedRpc

BASE='5bf3f245a6ac0146d3950e368ab6e3c22fef5a1c'


def original(path,package):
    source=subprocess.check_output(['git','show',BASE+':'+path],text=True)
    module=types.ModuleType(package+'._saved_baseline');module.__package__=package
    exec(compile(source,'git:'+BASE+':'+path,'exec'),module.__dict__)
    return module


def replay(root,*,baseline):
    counts=Counter();spans=[]
    state,h=state_at(root/'canonical.sqlite')
    try:
        if baseline:
            old=original('meme_machine/solana_selective_history.py','meme_machine')
            h.plan=types.MethodType(old.SelectiveHistory.plan,h)
        h.bind('pumpswap','rolling-pool')
        scope=program_scope('pumpswap')
        h.prove(IntervalProof(scope,100,120,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=120,lineage_hash=digest('saved-rolling-coverage')),NOW))
        h.request('pumpswap','rolling-pool',100,120,priority=3,deadline=NOW+150)
        # Both aliases are authenticated representations of one pool.
        h.bind('pumpswap','alias-pool',aliases=('authenticated-alias',))
        for address in ('alias-pool','authenticated-alias'):
            h.request('pumpswap',address,200,220,priority=3,deadline=NOW+150)
        # Another consumer asks for an overlapping, still unique tail.
        h.bind('pumpswap','tail-pool')
        for lo,hi in ((300,320),(310,330)):
            h.request('pumpswap','tail-pool',lo,hi,priority=3,deadline=NOW+150)
        while (planned:=h.plan()) is not None:
            job,_=planned;counts['getTransactionsForAddress']+=1
            spans.append([job['address'],job['lo'],job['hi']])
            h.commit_page(job,dict(data=[]),finalized_through=330);h.lifecycle.publish()
        coverage={a:h.rolling.missing('pumpswap',h.scope_for('pumpswap',a),lo,hi)
            for a,lo,hi in (('rolling-pool',100,120),('alias-pool',200,220),('authenticated-alias',200,220),('tail-pool',300,330))}
        assert all(not gaps for gaps in coverage.values())
    finally:state.writer.close()
    impl=original('meme_machine/lanes/pump/solana_immutable_rpc.py','meme_machine.lanes.pump') if baseline else solana
    url='https://solana-mainnet.g.alchemy.com/v2/'+('x'*32)
    impl.ImmutableReads(str(root/'existing-broker.sqlite'),url).finalized(120)
    def wire(self,request):
        values=[]
        for row in request if isinstance(request,list) else [request]:
            counts[row['method']]+=1
            value=1000+row['params'][0] if row['method']=='getBlockTime' else dict(context=dict(slot=120),value=[])
            values.append(dict(id=row['id'],result=value))
        return values if isinstance(request,list) else values[0]
    client=type('SavedRPC',(impl.ImmutableRPCMixin,RPC),dict(_http=wire))
    with patch.dict('os.environ',MM_SOLANA_EVIDENCE_BROKER_DB=str(root/'existing-broker.sqlite')):
        a=client(url,sleeper=lambda _:None);b=client(url,sleeper=lambda _:None)
        times=a.call_many('getBlockTime',[[100],[100],[101]])+b.call_many('getBlockTime',[[101],[100]])
        for r in (a,b):r.call('getMultipleAccounts',[['fresh-account'],dict(commitment='finalized')],True)
    impl=original('meme_machine/lanes/pons/immutable_rpc.py','meme_machine.lanes.pons') if baseline else pons
    store=impl.EvidenceStore();tx=dict(hash='tx',blockHash='block',**{'from':'0x'+'01'*20})
    try:
        def sender(method,params):counts[method]+=1;return tx.copy()
        for lane in ('current','survivor'):
            rpc=PacedRpc('https://unit.invalid/key',role='test',requests_per_second=2,transport=sender)
            rpc.evidence_reuse=impl.Reuse('https://unit.invalid/key',store,lane);rpc.evidence_receipts={'tx':'block'}
            assert rpc.call('eth_getTransactionByHash',['tx'])==tx
    finally:store.db.close()
    return dict(physical_rpc_elements=dict(counts),history_spans=spans,
        complete_coverage=coverage,block_times=times,transaction_sender=tx)


def main():
    network_guard()
    with Scratch() as scratch:
        root=Path(scratch.path)
        for name in ('before','after'):(root/name).mkdir()
        before=replay(root/'before',baseline=True);after=replay(root/'after',baseline=False)
        assert before['complete_coverage']==after['complete_coverage']
        assert before['block_times']==after['block_times']
        assert before['transaction_sender']==after['transaction_sender']
        weights=dict(getTransactionsForAddress=100,getBlockTime=20,getMultipleAccounts=20,eth_getTransactionByHash=20)
        removed={method:before['physical_rpc_elements'].get(method,0)-after['physical_rpc_elements'].get(method,0) for method in weights}
        cu=sum(weights[m]*n for m,n in removed.items())
        print(json.dumps(dict(schema='final-acquisition-saved-workload-v1',baseline_commit=BASE,
            classification='OFFLINE_SAVED_FIXTURES_NOT_ACCOUNT_BILLING',before=before,after=after,
            eliminated_rpc_elements=removed,avoided_cu=cu,avoided_usd=cu*.525/1000000,
            canonical_coverage_and_values_equal=True,market_calls=0),indent=2))
        scratch.check();scratch.success=True


if __name__=='__main__':main()
