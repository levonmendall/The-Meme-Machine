"""Synthetic native-API restoration attribution; never an AWS capacity proof."""
import cProfile
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import pstats
import sqlite3
import sys
import time
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

from operational import pump_restore_benchmark as fixture


def timed(call, count):
    wall, cpu = time.perf_counter(), time.process_time()
    value = call()
    return dict(calls=count, wall_seconds=time.perf_counter()-wall,
        cpu_seconds=time.process_time()-cpu), value


def audit_scope(root, output):
    counters = dict(archive_opens=0, archive_bytes_offered=0, network_calls=0)
    def audit(event, args):
        if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo'):
            counters['network_calls'] += 1
            raise RuntimeError('benchmark_network_forbidden')
        if event == 'sqlite3.connect':
            value = os.fsdecode(args[0])
            path = Path(unquote(urlsplit(value).path) if value.startswith('file:') else value).resolve()
            if not path.is_relative_to(root):
                raise RuntimeError('benchmark_foreign_database_forbidden')
        if event == 'open' and not isinstance(args[0],int):
            path = Path(os.fsdecode(args[0])).resolve()
            if args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):
                if path != output and not path.is_relative_to(root):
                    raise RuntimeError('benchmark_foreign_write_forbidden')
            elif path.suffix == '.zlib' and path.is_relative_to(root):
                counters['archive_opens'] += 1
                counters['archive_bytes_offered'] += path.stat().st_size
    sys.addaudithook(audit)
    return counters


def delta(before, after):
    return {key: delta(before.get(key,{}), value) if isinstance(value,dict)
            else value-before.get(key,0)
            for key,value in after.items() if isinstance(value,(dict,int,float))}


def vm_cost(db, sql, identity):
    ticks = [0]
    def progress():
        ticks[0] += 1
        return 0
    db.set_progress_handler(progress,1)
    try:
        result = db.execute(sql,(identity,)).fetchone()
    finally:
        db.set_progress_handler(None,0)
    return ticks[0], result


def lookup_cost(db, identities):
    sql = 'SELECT body,hash,archive FROM canonical_evidence WHERE identity=?'
    base = 'SELECT body,hash,archive FROM rolling_economic_events WHERE identity=?'
    selected = identities[:64]
    view_steps, base_steps = [], []
    for identity in selected:
        steps, expected = vm_cost(db,sql,identity)
        native_steps, actual = vm_cost(db,base,identity)
        if expected != actual:
            raise ValueError('benchmark_fixture_base_partition_mismatch')
        view_steps.append(steps);base_steps.append(native_steps)
    timing, rows = timed(lambda:[db.execute(sql,(identity,)).fetchone()
        for identity in identities for _ in range(4)],len(identities)*4)
    timing.update(vm_steps_min=min(view_steps),vm_steps_max=max(view_steps),
        native_base_vm_steps_min=min(base_steps),native_base_vm_steps_max=max(base_steps),
        selected_vm_queries=len(selected),
        explain=[row[3] for row in db.execute('EXPLAIN QUERY PLAN '+sql,(identities[0],))],
        note='Native base lookup is attribution comparator only; view precedence cannot be bypassed.')
    return timing,rows[::4]


def decomposition(shared, canonical):
    refs = shared.db.execute('SELECT body,hash FROM canonical_event_refs ORDER BY identity').fetchall()
    hot = canonical.execute('SELECT body,hash FROM canonical_evidence WHERE typeof(body)=\'text\' LIMIT 256').fetchall()
    steps = {}
    def decode_hash(rows):
        decoded=[]
        for raw,_ in rows:
            body=json.loads(raw)
            decoded.append((body,fixture.digest(body)))
        return decoded
    steps['reference_json_decode_hash'], decoded = timed(lambda:decode_hash(refs),len(refs))
    if any(value[1] != refs[index][1] for index,value in enumerate(decoded)):
        raise ValueError('benchmark_reference_hash_mismatch')
    if hot:
        steps['hot_text_json_decode_hash'], decoded_hot = timed(lambda:decode_hash(hot),len(hot))
        if any(value[1] != hot[index][1] for index,value in enumerate(decoded_hot)):
            raise ValueError('benchmark_hot_hash_mismatch')
        steps['hot_materialized_deepcopy'], _ = timed(lambda:[deepcopy(row[0]) for row in decoded_hot],len(hot))
        steps['hot_json_bytes'] = sum(len(raw.encode()) for raw,_ in hot)
    steps['reference_json_bytes'] = sum(len(raw.encode()) for raw,_ in refs)
    return steps


def profile_restore(built,counters):
    profiler = cProfile.Profile(timer=time.process_time)
    profiler.enable()
    result = fixture.restore_pass(built,counters)
    profiler.disable()
    stats = pstats.Stats(profiler)
    selected = []
    for (filename,line,function),(primitive,calls,own,cumulative,callers) in stats.stats.items():
        if 'meme_machine' in filename or function in ('deepcopy','dumps','loads'):
            selected.append(dict(module=Path(filename).name,line=line,function=function,
                calls=calls,self_cpu_seconds=own,cumulative_cpu_seconds=cumulative))
    return dict(scope='CPU_PROFILE_WITH_PROBE_OVERHEAD_NOT_CAPACITY',
        restore=result,top_self_cpu=sorted(selected,key=lambda r:r['self_cpu_seconds'],reverse=True)[:24])


def warm(built, corpus, count):
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_selective_source import install
    from meme_machine.solana_scoped_retirement import ScopedRetirement
    from meme_machine.runtime.candidate_history import CandidateHistory
    with closing(EvidenceWriter(built['source'],clock=lambda:corpus['clock'])) as writer:
        history=install(SimpleNamespace(writer=writer,fence=FinalizedFence(writer,
            endpoint_identity=corpus['endpoint_identity'])))
        history.clock=history.lifecycle.clock=lambda:corpus['clock']
        with closing(CandidateHistory(built['consumer'])) as shared:
            candidates=shared.candidates(lane='pump',event_prefix='pump_')
        retirement=ScopedRetirement(history)
        return sum(retirement.restore('pump',row['candidate']) for row in candidates[:count])


def cohort_migration(output):
    """Exercise unchanged remap predicates on an intact renamed synthetic cohort."""
    from unittest.mock import patch
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Scratch
    from meme_machine.runtime import candidate_history, operation_costs
    if sys.version_info[:3] != (3,12,14):
        raise ValueError('benchmark_pinned_python_required')
    network_guard();os.environ['MM_OPERATION_COST_DIAGNOSTICS']='1'
    output=Path(output).resolve()
    with Scratch() as scratch:
        counters=audit_scope(scratch.path,output)
        legacy=scratch.path/'legacy';legacy.mkdir()
        source=legacy/'shared';source.mkdir()
        corpus=fixture.capture_fixture(Path.cwd(),16,16,64,0)
        built=fixture.build_history(corpus,source);built['restore_at']=corpus['restore_at']
        warm(built,corpus,12)
        rows=[]
        def measure(label):
            before=operation_costs.snapshot()['rows']
            measured=fixture.restore_pass(built,counters)
            after=operation_costs.snapshot()['rows']
            rows.append(dict(mode=label,restore=measured,operation_delta=delta(before,after)))
        measure('original_native_locator')
        renamed=scratch.path/'aws-cohort'
        legacy.rename(renamed)
        built['source']=renamed/'shared/solana-evidence.sqlite'
        built['consumer']=renamed/'shared/solana-candidate-history.sqlite'
        with patch.object(candidate_history,'RETAINED_REFERENCE_LEGACY_ROOT',legacy), \
                patch.object(candidate_history,'RETAINED_REFERENCE_AWS_ROOT',renamed), \
                patch.dict(os.environ,MM_MODE='PAPER',
                    MM_PAPER_EPOCH=candidate_history.RETAINED_REFERENCE_EPOCH,
                    MM_STATE_ROOT=str(renamed),MM_SOLANA_EVIDENCE_PLANE_DB=str(built['source'])):
            measure('authenticated_cohort_relocation')
            profiled=profile_restore(built,counters)
        if rows[0]['restore']['output_sha256'] != rows[1]['restore']['output_sha256']:
            raise ValueError('benchmark_cohort_relocation_changed_economics')
        result=dict(schema='pump-cohort-path-cost-v1',scope=fixture.SCOPE,
            source_commit='0c8e9bea',python=sys.version,sqlite=sqlite3.sqlite_version,
            references=built['references'],candidates=16,text_fraction=.75,
            unmodified_original_references=True,fixture_roots_only_relocated=True,
            authentication_predicates_unchanged=True,network_calls=counters['network_calls'],
            cases=rows,cpu_profile=profiled)
        output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
        scratch.check();scratch.success=True
    print(json.dumps(dict(state='COMPLETE',output=str(output))))


def main():
    if sys.version_info[:3] != (3,12,14):
        raise ValueError('benchmark_pinned_python_required')
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Scratch
    from meme_machine.runtime.candidate_history import CandidateHistory
    from meme_machine.runtime import operation_costs
    network_guard()
    os.environ['MM_OPERATION_COST_DIAGNOSTICS']='1'
    output=Path(sys.argv[1]).resolve()
    result=dict(schema='pump-restore-query-cost-v1',scope=fixture.SCOPE,
        python=sys.version,sqlite=sqlite3.sqlite_version,source_commit='0c8e9bea',
        production_changes=False,network_calls=0,financial_state_access=False,cases=[])
    with Scratch() as scratch:
        counters=audit_scope(scratch.path,output)
        for candidates in (16,32,64):
            root=scratch.path/str(candidates);root.mkdir()
            corpus=fixture.capture_fixture(Path.cwd(),candidates,16,64,0)
            built=fixture.build_history(corpus,root);built['restore_at']=corpus['restore_at']
            for mode in ('all_cold','mixed','all_text'):
                if mode=='mixed':warm(built,corpus,candidates*3//4)
                if mode=='all_text':warm(built,corpus,candidates)
                with closing(sqlite3.connect(built['source'])) as canonical, \
                        closing(CandidateHistory(built['consumer'])) as shared:
                    ids=[json.loads(raw)['canonical_identity'] for raw, in shared.db.execute(
                        'SELECT body FROM canonical_event_refs ORDER BY identity')]
                    classes=dict(canonical.execute('SELECT typeof(body),count(*) FROM canonical_evidence GROUP BY typeof(body)'))
                    lookup,_=lookup_cost(canonical,ids)
                    pieces=decomposition(shared,canonical)
                before=operation_costs.snapshot()['rows']
                restored=fixture.restore_pass(built,counters)
                after=operation_costs.snapshot()['rows']
                if restored['restored'] != candidates:
                    raise ValueError('benchmark_restore_population_mismatch')
                row=dict(candidates=candidates,references=len(ids),mode=mode,classes=classes,
                    corpus_sha256=fixture.digest(corpus),lookup=lookup,pieces=pieces,
                    restore=restored,operation_delta=delta(before,after))
                if candidates==64 and mode=='mixed':row['cpu_profile']=profile_restore(built,counters)
                result['cases'].append(row)
                output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
                print(json.dumps(dict(candidates=candidates,mode=mode,
                    restore_wall_seconds=restored['wall_seconds'])),flush=True)
                scratch.check()
        result['network_calls']=counters['network_calls']
        output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
        scratch.check();scratch.success=True
    print(json.dumps(dict(state='COMPLETE',cases=len(result['cases']),output=str(output))))


if __name__=='__main__':main()
