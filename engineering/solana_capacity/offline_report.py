"""Publish small, verifiable receipts from volume-backed offline diagnostics.

Raw frames, databases, parity rows and syscall traces stay on the attached volume.
This command reads existing results and local source only; it performs no RPC.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import subprocess


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(1024*1024):h.update(chunk)
    return h.hexdigest()


def read(path):return json.loads(path.read_text())


def delivery_digest(path):
    from .offline_replay import frames
    h=hashlib.sha256();count=0;size=0
    for metadata,raw in frames(path):
        if metadata['kind']!='delivery':continue
        h.update(struct.pack('!I',len(raw)));h.update(raw);count+=1;size+=len(raw)
    return dict(digest=h.hexdigest(),messages=count,bytes=size)


def write(root,name,value):
    (root/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')


def allocator(value):
    p=value['performance']
    keys=('grant_latency','cpu_seconds','wall_seconds','process_io_delta','conservation',
          'errors','application_retries','missed_funding_ceiling_5s','durable_transactions',
          'begin_wait_over_1ms','database_files_bytes','requests','independent_authority_connections',
          'capital','replay_seconds')
    return {k:p[k] for k in keys}|dict(native_delivery_latency=value['native_delivery_latency'],
        worker_resources=value['worker_resources'])


def ingestion(value):
    return {k:value[k] for k in ('cpu_seconds','wall_seconds','rss_peak_kib','canonical_count',
        'canonical_digest','output_digests','process_io_delta','sqlite_changes','pending','limitations')}


def report(evidence,baseline,candidate,out):
    from meme_machine.shared_capital import RiskPolicy
    from meme_machine.shared_capital.model import digest
    out.mkdir(parents=True,exist_ok=True)
    corrected=read(evidence/'corrected-attribution-final.json')
    original=read(evidence/'original-attribution-final.json')
    write(out,'BYTE_LATENCY.json',corrected);write(out,'PRIOR_CAPTURE.json',original)
    paths={};parity={};contention={}
    for name in ('baseline','repaired'):
        root=evidence/('contention-'+name);x=read(root/'result.json')
        parity[name]=read(root/'ingestion-alone/parity.json')
        paths[name]=dict(result=str(root/'result.json'),result_sha256=sha(root/'result.json'),
            parity=str(root/'ingestion-alone/parity.json'),parity_sha256=sha(root/'ingestion-alone/parity.json'))
        maxima={}
        for row in x['sampled_whole_process_resources']:
            for pid,v in row['processes'].items():maxima[pid]=max(maxima.get(pid,0),v['cpu_seconds'])
        contention[name]=dict(host=x['host'],provider_calls=x['provider_calls'],
            combined_seconds=x['combined_seconds'],load_cycles=x['load_cycles'],exit_codes=x['exit_codes'],
            sampled_group_cpu_lower_bound=sum(maxima.values()),
            observed_peak_process_group_rss_bytes=x['observed_peak_process_group_rss_bytes'],
            allocator_alone=allocator(x['allocator_alone']),allocator_combined=allocator(x['allocator_combined']),
            pons_alone=x['pons_alone'],pons_combined=x['pons_combined'],
            ingestion_alone=ingestion(x['ingestion_alone']),combined_ingestion=[ingestion(v) for v in x['combined_ingestion']],
            limitations=x['limitations']+['Group CPU from /proc is a sampled lower bound; import and final unsampled work cannot be recovered exactly.'])
    if parity['baseline']!=parity['repaired']:raise ValueError('identical_tape_parity_failed')
    dbpath=Path(corrected['capture'])/'state/canonical.sqlite'
    with sqlite3.connect(dbpath.as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        rows=[list(r) for r in db.execute('SELECT identity,scope,slot,signature,transaction_index,event_index,hash,first_seen,body FROM canonical_evidence ORDER BY scope,slot,transaction_index,event_index,identity')]
    tape=parity['baseline']['canonical']
    if [r[:8] for r in rows]!=[r[:8] for r in tape]:raise ValueError('capture_canonical_identity_order_or_clock_changed')
    if any(a[8]!=b[8] for a,b in zip(rows,tape) if a[8] is not None):raise ValueError('capture_retained_body_changed')
    write(out,'PARITY.json',dict(schema='pump-provider-parity-receipt-v1',provider_calls=0,
        exact_baseline_repaired_rows_equal=True,canonical_count=len(tape),
        canonical_digest=contention['baseline']['ingestion_alone']['canonical_digest'],
        capture_identity_signature_indices_hash_first_seen_equal=True,
        captured_retained_bodies_equal=sum(r[8] is not None for r in rows),
        captured_bodies_previously_retired=sum(r[8] is None for r in rows),
        output_digests=contention['baseline']['ingestion_alone']['output_digests'],
        output_counts={k:len(v) for k,v in parity['baseline']['outputs'].items()},
        pending=contention['baseline']['ingestion_alone']['pending'],artifacts=paths,
        limitation='Frozen tape lacks complete qualification windows and positions; unchanged offline economic fixtures supply regression evidence only.'))
    write(out,'CONTENTION.json',dict(schema='pump-provider-contention-receipt-v1',**contention))
    raw_receipts={name:delivery_digest(evidence/('processing-'+name+'-final')/'observer.frames.zlib') for name in ('baseline','repaired')}
    raw_receipts['capture']=delivery_digest(Path(corrected['capture'])/'provider.frames.zlib')
    if raw_receipts['baseline']!=raw_receipts['capture'] or raw_receipts['repaired']!=raw_receipts['capture']:
        raise ValueError('observer_raw_delivery_parity_failed')
    processing={name:read(evidence/('processing-'+name+'-final')/'result.json') for name in ('baseline','repaired')}
    if processing['baseline']['observer']['ws_header_digest']!=processing['repaired']['observer']['ws_header_digest']:
        raise ValueError('observer_header_parity_failed')
    write(out,'PROCESSING.json',dict(schema='pump-provider-processing-receipt-v1',
        raw_delivery_receipts=raw_receipts,**processing))
    tracked=subprocess.check_output(['git','ls-files'],cwd=baseline,text=True).splitlines()
    frozen=[p for p in tracked if p.startswith('meme_machine/shared_capital/') or
        p in read(baseline/'operational/shared-capital-activation/PRESERVATION.json')['byte_identical_to_published_candidate'] or
        p in ('meme_machine/lanes/pons/provider_admission.py','meme_machine/solana_candidate_join.py',
              'meme_machine/solana_stable_shards.py','meme_machine/solana_evidence_runtime.py',
              'meme_machine/runtime/evidence_worker.py','operational/shared-capital-activation/risk-policy.proposed.json')]
    changed={'meme_machine/solana_selective_history.py','meme_machine/solana_selective_source.py'}
    hashes={p:sha(baseline/p) for p in frozen if p not in changed}
    if any(sha(candidate/p)!=h for p,h in hashes.items()):raise ValueError('frozen_source_changed')
    policy=digest(RiskPolicy(**read(candidate/'operational/shared-capital-activation/risk-policy.proposed.json')).value())
    if policy!='e87385900145e53956df18956ee2390f0d95787e6ffc44243251f9b147eb65f2':raise ValueError('approved_policy_changed')
    preserved={}
    for label in ('corrected','original'):
        old=read(evidence/(label+'-attribution.json'))['preserved_capture_manifest']
        new=(corrected if label=='corrected' else original)['preserved_capture_manifest']
        if any(new.get(k)!=v for k,v in old.items()):raise ValueError('existing_capture_changed')
        preserved[label]=dict(all_existing_capture_bytes_unchanged=True,
            added_sidecars={k:v for k,v in new.items() if k not in old},
            note='Read-only SQLite inspection created empty WAL/SHM sidecars; no existing evidence was modified or removed.')
    write(out,'PRESERVATION.json',dict(schema='pump-provider-preservation-v1',
        starting_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=baseline,text=True).strip(),
        starting_tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=baseline,text=True).strip(),
        approved_policy_sha256=policy,original_paper_epoch='paper-1791089005190643467',
        frozen_file_sha256=hashes,native_strategy_contracts=read(baseline/'operational/shared-capital-activation/PRESERVATION.json')['native_strategy_contracts'],
        captures=preserved,deliberate_source_repairs=sorted(changed|{'meme_machine/solana_source_intake.py','meme_machine/lanes/pons/pons_survivor_runtime.py'}),
        deployment_performed=False,epoch_opened=False,provider_calls=0,startup_blocker='combined_position_and_candidate_provider_latency_not_certified'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','baseline','candidate','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();report(*(Path(getattr(a,k)).resolve() for k in ('evidence','baseline','candidate','output')))


if __name__=='__main__':main()
