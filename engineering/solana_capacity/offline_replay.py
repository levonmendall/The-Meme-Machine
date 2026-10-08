"""Replay recorded native deliveries through the real join and canonical owner.

No provider requests or synthesized coverage. Incomplete tape tails stay pending.
Use --source to compare a frozen worktree with a repaired one. Only stored raw
frames and their original wall observations enter authority; replay time is a
separate performance clock.
"""
import argparse
from collections import Counter
import cProfile
import hashlib
import json
import os
from pathlib import Path
import pstats
import resource
import sqlite3
import struct
import sys
import time
from types import SimpleNamespace
import zlib


def frames(path):
    d=zlib.decompressobj(); pending=b''
    with path.open('rb') as f:
        while chunk:=f.read(65536):
            pending+=d.decompress(chunk)
            while len(pending)>=8:
                h,n=struct.unpack('!II',pending[:8])
                if h>65536 or n>16*1024*1024:raise ValueError('capture_record_bound')
                end=8+h+n
                if len(pending)<end:break
                yield json.loads(pending[8:8+h]),pending[8+h:end]
                pending=pending[end:]
    pending+=d.flush()
    if pending or not d.eof or d.unused_data:raise ValueError('capture_incomplete')


def io():
    return {k:int(v) for k,v in (line.split(':') for line in Path('/proc/self/io').read_text().splitlines())}


def digest_rows(rows):
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def replay(source,capture,out):
    sys.path.insert(0,str(source)); os.environ['MM_OPERATIONAL_PHASE']='BOUNDED_PROVIDER_PROOF'
    out.mkdir(parents=True,exist_ok=False); path=out/'canonical.sqlite'
    os.environ.update(TMPDIR=str(out),SQLITE_TMPDIR=str(out))
    os.environ['MM_SOLANA_CANDIDATE_HISTORY_DB']=str(out/'candidate.sqlite')
    from operational.tests import network_guard
    network_guard()
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_selective_source import install,commit_scout,commit_control,commit_candidates
    from meme_machine.solana_candidate_join import CandidateTransactionJoin
    from meme_machine.yellowstone import geyser_pb2 as pb
    try:
        from meme_machine.solana_source_intake import candidate_log_message
    except ImportError: candidate_log_message=None
    result=json.loads((capture/'result.json').read_text()); wall=[result['measurement_started']]
    writer=EvidenceWriter(path,clock=lambda:wall[0]); state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity=result['endpoint_identity']))
    h=install(state); h.clock=lambda:wall[0]; h.lifecycle.clock=h.clock
    profiles=cProfile.Profile(); subscriptions={}; joins={}; ws_open={}; ws_ids={}; early_logs=[]
    counters=Counter(); commits=[]; durations=[]; source_files={}
    for file in result['source_sha256']:
        p=source/file
        if p.exists():source_files[file]=hashlib.sha256(p.read_bytes()).hexdigest()
    initial=io(); cpu=time.process_time(); start=time.monotonic(); profiles.enable()
    def commit(frame,sid):
        if frame is None:return
        sub=subscriptions[sid]; before=time.monotonic()
        if sub['addresses']:commit_candidates(state,frame,sub['addresses'],sid,publish=False)
        else:commit_control(state,frame)
        duration=time.monotonic()-before; durations.append(duration)
        commits.append(dict(slot=frame.update.block.slot,session=sid,seen=frame.seen,seconds=duration,events=len(frame.log_transactions),statuses=len(frame.candidate_statuses)))
        h.lifecycle.publish()
    try:
        for meta,raw in frames(capture/'provider.frames.zlib'):
            kind=meta['kind']
            if kind=='subscribe':
                req=pb.SubscribeRequest.FromString(raw); sid=meta['id']
                addresses={a:scope for scope in ('pump','pumpswap') for a in meta['addresses'] if a==__import__('meme_machine.solana_selective_history',fromlist=['PROGRAMS']).PROGRAMS[scope]}
                from meme_machine.solana_rolling_history import program_scope
                addresses={a:program_scope(f) for a,f in addresses.items()}
                subscriptions[sid]=dict(scout=bool(req.accounts),addresses=addresses)
                if not req.accounts:
                    join=CandidateTransactionJoin(addresses,set(),clock=lambda:0.,filtered_from_slot=req.from_slot,max_join_seconds=120)
                    joins[sid]=join
                    if addresses:
                        for slot,sig,logs,seen in early_logs:commit(join.feed_log(slot,sig,logs,None,seen),sid)
                continue
            if kind=='websocket_open':ws_open[meta['id']]=meta['addresses'];continue
            if kind!='delivery':continue
            wall[0]=meta['seen']; counters[meta['transport']+'_received_bytes']+=len(raw)
            if meta['transport']=='yellowstone':
                update=pb.SubscribeUpdate.FromString(raw)
                if subscriptions[meta['id']]['scout']:commit_scout(state,update,wall[0])
                else:commit(joins[meta['id']].feed(update,len(raw),wall[0]),meta['id'])
            else:
                # These are the exact old/new source intake operations.
                if candidate_log_message is None:
                    json.loads(raw); value=json.loads(raw)
                else:value=candidate_log_message(raw,max_bytes=16*1024*1024)
                if 'id' in value:
                    ws_ids[meta['id'],value['result']]=ws_open[meta['id']][value['id']-1];continue
                params=value['params']; v=params['result']['value']; slot=params['result']['context']['slot']
                if v['err'] is not None:continue
                matched=False
                for sid,join in joins.items():
                    if ws_ids[meta['id'],params['subscription']] in subscriptions[sid]['addresses']:
                        matched=True;commit(join.feed_log(slot,v['signature'],v['logs'],None,wall[0]),sid)
                if not matched:early_logs.append((slot,v['signature'],v['logs'],wall[0]))
        while h.lifecycle.flush():pass
        h.lifecycle.publish()
        canonical=[list(r) for r in writer.db.execute('SELECT identity,scope,slot,signature,transaction_index,event_index,hash,first_seen,body FROM canonical_evidence ORDER BY scope,slot,transaction_index,event_index,identity')]
        outputs={name:[list(r) for r in writer.db.execute('SELECT * FROM '+name+' ORDER BY 1,2')] for name in
                 ('market_observations','candidate_lifecycle','evidence_bindings','rolling_origins','candidate_checkpoints','candidate_coverage','candidate_gaps','candidate_pending_proofs')}
        # Compression bytes in coverage rows are deterministic but not JSON values.
        outputs={k:[[x.hex() if isinstance(x,bytes) else x for x in row] for row in rows] for k,rows in outputs.items()}
        h.lifecycle.publish()
        if (out/'candidate.sqlite').exists():
            with sqlite3.connect(out/'candidate.sqlite') as db:
                for name in ('canonical_event_refs','candidates','work'):
                    if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone():continue
                    rows=[list(r) for r in db.execute('SELECT * FROM '+name+' ORDER BY 1')]
                    if name=='canonical_event_refs':
                        for row in rows:
                            ref=json.loads(row[8])
                            if digest_rows(ref)!=row[9]:raise ValueError('reference_checksum_invalid')
                            ref['path']='<canonical.sqlite>'
                            row[8]=json.dumps(ref,sort_keys=True,separators=(',',':'));row[9]=digest_rows(ref)
                    outputs['consumer:'+name]=[[x.replace(str(path),'<canonical.sqlite>') if isinstance(x,str) else x for x in row] for row in rows]
        pending={sid:dict(slots=len(join.pending),bytes=join.pending_bytes,missing_logs=sum(len(s['missing_logs']) for s in join.pending.values()),early_logs=len(join.early_logs)) for sid,join in joins.items()}
        profiles.disable(); elapsed=time.monotonic()-start; process_cpu=time.process_time()-cpu; final=io()
        profiles.dump_stats(str(out/'profile.pstats'))
        with (out/'profile.txt').open('w') as f:pstats.Stats(profiles,stream=f).strip_dirs().sort_stats('cumulative').print_stats(35)
        projection=dict(canonical=canonical,outputs=outputs)
        (out/'parity.json').write_text(json.dumps(projection,sort_keys=True,indent=2)+'\n')
        measured=dict(schema='pump-provider-identical-tape-v1',source=str(source),capture=str(capture),source_files=source_files,provider_calls=0,
            canonical_identities=[r[0] for r in canonical],canonical_count=len(canonical),canonical_digest=digest_rows(canonical),
            output_digests={k:digest_rows(v) for k,v in outputs.items()},pending=pending,counters=dict(counters),commits=commits,
            wall_seconds=elapsed,cpu_seconds=process_cpu,rss_peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            process_io_delta={k:final[k]-initial[k] for k in initial},sqlite_changes=writer.db.total_changes,
            limitations=['Replay executes captured deliveries serially; original scheduling and network/finality delays are not replayed.', 'Profiler overhead is included equally in comparisons.', 'Missing tape tail remains pending and confers no completeness.', 'Consumer qualification and position economics require additional unchanged fixture tests.'])
        (out/'result.json').write_text(json.dumps(measured,sort_keys=True,indent=2)+'\n')
        print(json.dumps({k:v for k,v in measured.items() if k in ('canonical_count','canonical_digest','pending','wall_seconds','cpu_seconds','sqlite_changes','process_io_delta')},indent=2))
    finally:writer.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--capture',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();replay(Path(a.source).resolve(),Path(a.capture).resolve(),Path(a.output).resolve())


if __name__=='__main__':main()
