"""Bounded synthetic order tape; no provider calls, performance/alpha claim."""
import json
import resource
import tempfile
import time
from pathlib import Path
from meme_machine.store import Store,encode
from meme_machine.dlmm_paper import Replay
from meme_machine.provider import RPC
from tests.dlmm_support import snapshot,event


def main():
    started=time.monotonic();samples=[]
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'dlmm.db';s=Store(path,'synthetic',100_000_000,'DLMM resources')
        r=Replay(s);r.reserve('lp',snapshot(),100);r.deposit('lp',snapshot(),100)
        r.process('lp',event(s.state['liquidity_positions']['lp'],450_000_000))
        seq=s.state['journal_seq']
        rpc=RPC('https://test.invalid',transport=lambda req:dict(result={'data':'x'*4000}),clock=lambda:0)
        for i in range(6000):
            p=s.state['liquidity_positions']['lp']
            r.process('lp',event(p,1_000_000,i%2==0))
            # Expired/new keys exercise actual existing provider cache eviction.
            rpc._cache_put(str(i),{'data':'x'*4000})
            if i in (2999,5999):
                s.reconcile();s.verify_archive()
                samples.append(dict(events=i+1,**s.journal_stats(),state_bytes=len(encode(s.state)),
                    rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
        assert s.state['journal_seq']-seq==6000  # one atomic checkpoint per admitted order
        assert samples[-1]['rows']<=4096
        assert samples[-1]['db_bytes']+samples[-1]['wal_bytes']<32*1024*1024
        assert samples[-1]['state_bytes']<150000
        assert samples[-1]['state_bytes']<samples[0]['state_bytes']+4096
        assert samples[-1]['rss_kib']<200*1024
        assert samples[-1]['rss_kib']<samples[0]['rss_kib']+16*1024
        assert samples[-1]['db_bytes']<samples[0]['db_bytes']+2*1024*1024
        assert len(rpc.cache)<=128 and rpc.cache_bytes<=8*1024*1024
        now=s.state['liquidity_positions']['lp']['last_time']
        mark=r.mark('lp',now);assert mark['resolved']
        r.exit_intent('lp','resource_end',now);r.withdraw('lp',now);settlement=r.settle('lp',now)
        s.close();s=Store(path,'synthetic',100_000_000,'DLMM resources');s.reconcile();s.verify_archive();s.close()
    result=dict(label='synthetic DLMM resource proof',events=6001,samples=samples,
        atomic_writes_per_event=1,dedup_records=0,cursor_integers=3,cache_entries=len(rpc.cache),
        cache_bytes=rpc.cache_bytes,real_provider_calls=0,elapsed_seconds=round(time.monotonic()-started,3),
        settlement_realized_lamports=settlement['realized'],
        limitation='temporary filesystem; bounded retention and process RSS, not physical-disk durability or live throughput')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
