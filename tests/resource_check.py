"""Bounded local rejection/intake workload, not continuous-market certification."""
import json
import os
import resource
import tempfile
import time
from pathlib import Path
from meme_machine.store import Store
from meme_machine.engine import Engine
from meme_machine.provider import RPC,Unavailable
from tests.support import SCOUT,event,evidence


def main():
    start=time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        path=str(Path(tmp)/'load.db')
        s=Store(path,'synthetic',100_000_000,'resource synthetic')
        e=Engine(s,[SCOUT])
        ev=evidence();ev['covered']=False
        for i in range(2000):
            now=100+i
            events=[event(now,id=f'{i}-{j}') for j in range(120)]
            e.scout(events,now)
            e.consider(event(now,id=f'reject-{i}'),ev,now)
        db=os.path.getsize(path)
        wal=os.path.getsize(path+'-wal')
        status=e.status(now)
        assert len(s.state['seen'])<=1000 and len(s.state['decisions'])<=100 and len(s.state['gaps'])<=20
        assert s.state['cash']==s.state['initial'] and not s.state['positions']
        s.reconcile()
        result=dict(label='synthetic bounded intake/rejection workload',frames=2000,submitted_events=240000,
            admitted_events_per_frame=100,db_bytes=db,wal_bytes=wal,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            elapsed_seconds=round(time.monotonic()-start,3),seen=len(s.state['seen']),decisions=len(s.state['decisions']),
            gaps=len(s.state['gaps']),journal_rows=s.state['journal_seq'],real_provider_calls=0,
            limitation='temporary filesystem; not continuous-market or physical disk durability proof')
        assert db+wal < 32*1024*1024
        assert result['peak_rss_kib'] < 200*1024
        print(json.dumps(result,sort_keys=True))
        s.close()
if __name__=='__main__':main()
