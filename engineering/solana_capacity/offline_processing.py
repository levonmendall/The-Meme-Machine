"""Isolate decode, capture observer and unchanged-request costs on one tape."""
import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import pstats
import resource
import sqlite3
import sys
import time
from types import SimpleNamespace
if __package__:
    from .offline_replay import frames, io, digest_rows
else:
    from offline_replay import frames, io, digest_rows


def measure(source,capture,out):
    sys.path.insert(0,str(source));os.environ['MM_OPERATIONAL_PHASE']='BOUNDED_PROVIDER_PROOF'
    out.mkdir(parents=True,exist_ok=False);os.environ.update(TMPDIR=str(out),SQLITE_TMPDIR=str(out))
    os.environ['MM_SOLANA_CANDIDATE_HISTORY_DB']=str(out/'candidate.sqlite')
    from operational.tests import network_guard
    network_guard()
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_selective_source import install
    from meme_machine.yellowstone import geyser_pb2 as pb
    from engineering.solana_capacity.transport_meter import TransportMeter
    try:from engineering.solana_capacity.transport_meter import websocket_metadata
    except ImportError:websocket_metadata=None
    try:from meme_machine.solana_source_intake import candidate_log_message
    except ImportError:candidate_log_message=None
    tape=list(frames(capture/'provider.frames.zlib'));ws=[r for m,r in tape if m.get('transport')=='websocket' and m['kind']=='delivery']
    timings=[];checksum=None;python_log_bytes=0;python_log_lines=0
    for repeat in range(3):
        cpu=time.process_time();wall=time.monotonic()
        if candidate_log_message is None:
            decoded=[]
            for raw in ws:json.loads(raw);decoded.append(json.loads(raw))
        else:decoded=[candidate_log_message(raw,max_bytes=16*1024*1024) for raw in ws]
        timings.append(dict(cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-wall))
        if repeat==0:
            h=hashlib.sha256()
            for v in decoded:
                if 'params' in v:
                    value=v['params']['result']['value']
                    python_log_bytes+=sum(len(x.encode()) for x in value.get('logs',[]));python_log_lines+=len(value.get('logs',[]))
                    if value['err'] is not None:value.pop('logs',None)
                h.update(json.dumps(v,sort_keys=True,separators=(',',':')).encode())
            checksum=h.hexdigest()
        del decoded
    meter=TransportMeter(out/'observer.frames.zlib');cpu=time.process_time();wall=time.monotonic();profile=cProfile.Profile();profile.enable()
    for m,raw in tape:
        kind=m['kind'];value=None
        if kind=='subscribe':value=dict(stream_id=m['id'],family=m['family'],request=pb.SubscribeRequest.FromString(raw))
        elif kind=='websocket_open':value=dict(stream_id=m['id'],addresses=m['addresses'])
        elif kind=='unsubscribe':value=dict(stream_id=m['id'])
        elif kind=='delivery':value=dict(stream_id=m['id'],family=m['family'],transport=m['transport'],raw=raw,seen=m['seen'])
        elif kind.startswith('membership_') or kind in ('rolling_retry','owner_backpressure'):value={k:v for k,v in m.items() if k not in ('kind','at')}
        if value is not None:meter(kind,value)
    meter.close();profile.disable();observer=dict(cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-wall,compressed_bytes=(out/'observer.frames.zlib').stat().st_size)
    header_digest=hashlib.sha256();observer_log_bytes=0
    for raw in ws:
        v=json.loads(raw);expected=dict(message='ack' if 'id' in v else v.get('method'))
        if 'params' in v:
            result=v['params']['result'];expected.update(slot=result['context']['slot'],signature=result['value'].get('signature'))
            observer_log_bytes+=sum(len(line.encode()) for line in result['value'].get('logs',[]))
        actual=expected if websocket_metadata is None else websocket_metadata(raw)
        if actual!=expected:raise ValueError('observer_routing_metadata_parity_failed')
        header_digest.update(json.dumps(actual,sort_keys=True,separators=(',',':')).encode())
    observer.update(ws_header_digest=header_digest.hexdigest(),raw_ws_bytes=sum(map(len,ws)),
        ws_python_log_bytes_materialized=observer_log_bytes if websocket_metadata is None else 0)
    with (out/'observer-profile.txt').open('w') as f:pstats.Stats(profile,stream=f).strip_dirs().sort_stats('cumulative').print_stats(20)
    with sqlite3.connect((capture/'state/canonical.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        jobs=db.execute('SELECT family,address,lo,hi,priority,deadline,id FROM acquisition_jobs ORDER BY created,id').fetchall()
        reassertions=db.execute("SELECT job,at FROM acquisition_observations WHERE kind='capacity_pressure' AND job IS NOT NULL ORDER BY at,rowid").fetchall()
    clock=[json.loads((capture/'result.json').read_text())['measurement_started']]
    writer=EvidenceWriter(out/'request.sqlite',clock=lambda:clock[0]);state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity='a'*64));history=install(state);history.clock=lambda:clock[0];history.lifecycle.clock=history.clock
    try:
        for family,address,lo,hi,priority,deadline,identity in jobs:history.request(family,address,lo,hi,priority=priority,deadline=deadline)
        by_id={j[-1]:j for j in jobs};changes=writer.db.total_changes;initial=io();cpu=time.process_time();wall=time.monotonic()
        for identity,at in reassertions:
            clock[0]=at;family,address,lo,hi,priority,deadline,_=by_id[identity]
            history.request(family,address,lo,hi,priority=priority,deadline=deadline)
        final=io();requests=dict(calls=len(reassertions),cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-wall,sqlite_changes=writer.db.total_changes-changes,
            process_io_delta={k:final[k]-initial[k] for k in initial},job_projection_digest=digest_rows([list(r) for r in writer.db.execute('SELECT * FROM acquisition_jobs ORDER BY id')]),
            observations=writer.db.execute('SELECT COUNT(*) FROM acquisition_observations').fetchone()[0])
    finally:writer.close()
    result=dict(source=str(source),capture=str(capture),provider_calls=0,decode_trials=timings,semantic_digest=checksum,python_materialized_log_bytes=python_log_bytes,python_materialized_log_lines=python_log_lines,
        physical_ws_bytes=sum(map(len,ws)),source_ws_parse_passes=2 if candidate_log_message is None else 1,observer=observer,requests=requests,rss_peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        limitations=['Observer profiling overhead is included; production observer settings remain unchanged.', 'Request replay uses the captured final immutable bounds/priority/deadline and repeated pressure observations; original unrecorded caller arguments cannot be recovered.', 'Source JSON validation still scans full physical payload; materialized string savings are local only.'])
    (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(json.dumps(result,indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--capture',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();measure(Path(a.source).resolve(),Path(a.capture).resolve(),Path(a.output).resolve())


if __name__=='__main__':main()
