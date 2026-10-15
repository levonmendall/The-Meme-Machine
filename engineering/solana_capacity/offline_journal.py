"""Attribute actual successful per-file writes from bounded offline strace logs.

Trace with -f -yy -s 0 -e trace=write,pwrite64,fdatasync,fsync. This tool does not
run providers or attach to services. Traced timings are not performance evidence.
"""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import re


def trace(path,parity):
    writes=defaultdict(Counter);syncs=Counter();errors=Counter();unparsed=0
    h=hashlib.sha256()
    with path.open('rb') as f:
        for raw in f:
            h.update(raw);line=raw.decode()
            found=re.search(r'\b(write|pwrite64)\(\d+<([^>]+)>.*\)\s+=\s+(\d+)',line)
            if found:
                method,name,count=found.groups();name=Path(name).name
                if name.startswith('etilqs_'):name='<sqlite-temporary-sort>'
                writes[name]['bytes']+=int(count);writes[name]['calls']+=1
                continue
            found=re.search(r'\b(fdatasync|fsync)\(\d+<([^>]+)>\)\s+=\s+0',line)
            if found:syncs[Path(found[2]).name]+=1;continue
            if '= -1' in line:errors[line.split('= -1',1)[1].split()[0]]+=1
            elif re.search(r'\b(write|pwrite64|fsync|fdatasync)\(',line):unparsed+=1
    if unparsed:raise ValueError('unparsed_syscall_receipts')
    p=json.loads(parity.read_text());body_bytes=sum(len(r[8].encode()) for r in p['canonical'] if r[8] is not None)
    wal=sum(v['bytes'] for k,v in writes.items() if k.endswith('-wal'))
    return dict(trace=str(path),trace_bytes=path.stat().st_size,trace_sha256=h.hexdigest(),
        writes=dict(writes),successful_syncs=dict(syncs),syscall_errors=dict(errors),
        canonical_event_body_bytes=body_bytes,total_wal_written_bytes=wal,
        wal_per_canonical_body_byte=wal/body_bytes,
        limitation='Actual successful syscall bytes in a profiled serial offline replay. Not original provider-proof WAL traffic; trace overhead invalidates latency comparisons. FD writes exclude mmap SHM and block-layer rounding.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();root=Path(a.evidence)
    result={name:trace(root/('journal-'+name+'.strace'),root/('journal-'+name)/'parity.json') for name in ('baseline','repaired')}
    for name,value in result.items():
        if value['syscall_errors']:raise ValueError(name+'_write_or_sync_error')
    Path(a.output).write_text(json.dumps(dict(schema='pump-provider-offline-journal-v1',provider_calls=0,**result),sort_keys=True,indent=2)+'\n')


if __name__=='__main__':main()
