"""Read-only observation of the real owner, including normal running drain.

The constructor hook records the production owner instance. It changes neither
admission, scheduling, queue limits, nor transaction execution. Sampling does
not enqueue health commands on the owner it is measuring.
"""
import json
import os
import resource
import threading
import time
import zlib
from pathlib import Path


class CompressedText:
    def __init__(self,path):
        self.file=path.open('wb');self.codec=zlib.compressobj(6)
    def write(self,text):self.file.write(self.codec.compress(text.encode()))
    def flush(self):self.file.flush()
    def close(self):
        self.file.write(self.codec.flush());self.file.close()


def normal_drain(samples,release,close,capacity):
    """Shutdown samples cannot satisfy a live drain; declining depth is required."""
    live=[r for r in samples if release is not None and release<=r['at']<=close and not r['closed']]
    if not live:return dict(proven=False,reason='no_running_post_release_samples')
    peak=max(live,key=lambda r:r['depth']);later=[r for r in live if r['at']>peak['at']]
    baseline=sorted(r['depth'] for r in live[:min(100,len(live))])[min(100,len(live))//2]
    # The observed ordinary baseline is capped at half capacity: a persistently
    # full queue cannot define itself as a healthy baseline.
    baseline=min(baseline,capacity//2)
    half=next((r for r in later if r['depth']<=capacity/2),None)
    base=next((r for r in later if r['depth']<=baseline and r['completed']>peak['completed']),None)
    tail=[r for r in live if r['at']>=close-10]
    stable=bool(tail) and tail[-1]['at']-tail[0]['at']>=9 and max(r['depth'] for r in tail)<=capacity/2
    return dict(proven=bool(peak['depth']>baseline and half and base and stable),peak_depth=peak['depth'],peak_at=peak['at'],
        ordinary_baseline_depth=baseline,peak_to_half_seconds=None if half is None else half['at']-peak['at'],
        peak_to_baseline_seconds=None if base is None else base['at']-peak['at'],
        normal_tail_stable=stable,normal_tail_seconds=0 if not tail else tail[-1]['at']-tail[0]['at'],
        tail_depths=[r['depth'] for r in tail],last_running_depth=live[-1]['depth'])


class LiveProbe:
    def __init__(self,path):
        self.path=Path(path);self.samples=[];self.owners=[];self.stop=threading.Event();self.thread=None
    def install(self):
        from meme_machine.solana_evidence_control import PriorityOwner
        self.original=PriorityOwner.__init__;probe=self
        def observed(owner,*args,**kwargs):
            probe.original(owner,*args,**kwargs);probe.owners.append(owner)
        PriorityOwner.__init__=observed
        self.thread=threading.Thread(target=self.run,name='read-only-proof-sampler',daemon=True);self.thread.start()
    def run(self):
        while not self.stop.wait(.05):
            for owner in self.owners:
                with owner.cv:
                    now=owner.clock();metrics=dict(owner.metrics)
                    row=dict(at=time.time(),depth=len(owner.queue),capacity=owner.capacity,closed=owner.closed,
                        busy=owner._checkpoint_busy,checkpoint_handoff=owner._checkpoint_handoff is not None,
                        oldest_wait=max((now-t for t in owner.enqueued.values()),default=0),
                        priorities={str(p):sum(r[0]==p for r in owner.queue) for p in range(5)},
                        completed=sum(v for k,v in metrics.items() if k.endswith('.completed')),
                        refused=metrics.get('rejected',0),admission_waited=metrics.get('admission_waited',0),
                        admission_wait_peak_us=metrics.get('admission_wait_peak_us',0))
                row['cpu_seconds']=time.process_time()
                row['rss_peak_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if len(self.samples)%20==0:
                    try:
                        row['rss_kib']=int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')//1024
                        row['process_io']={k:int(v) for k,v in (line.split(':') for line in Path('/proc/self/io').read_text().splitlines())}
                        row['child_cpu_seconds']=sum(resource.getrusage(resource.RUSAGE_CHILDREN)[:2])
                    except OSError:pass
                self.samples.append(row)
    def close(self):
        from meme_machine.solana_evidence_control import PriorityOwner
        self.stop.set();self.thread.join(timeout=2);PriorityOwner.__init__=self.original
        output=CompressedText(self.path)
        for row in self.samples:output.write(json.dumps(row)+'\n')
        output.close()
