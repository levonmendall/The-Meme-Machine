"""Exact synthetic cohort: original, duplicate-elision and factored path proof.

Each mode calls the actual Pump runner over the identical native FULL/ACK and
retired fixture. Only the explicitly compared filesystem-proof function varies.
No provider, financial database, canonical hash or cancellation proof is replaced.
"""
import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote,urlsplit

from operational import pump_restore_benchmark as fixture

PREDECESSOR='0c8e9beae8eed6e4579f4473c4f449f711fb5691'


def audit_scope(root,output):
    counts=dict(archive_opens=0,archive_bytes_offered=0,network_calls=0)
    def audit(event,args):
        if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo'):
            counts['network_calls']+=1;raise RuntimeError('benchmark_network_forbidden')
        if event=='sqlite3.connect':
            value=os.fsdecode(args[0]);path=Path(unquote(urlsplit(value).path) if value.startswith('file:') else value).resolve()
            if not path.is_relative_to(root):raise RuntimeError('benchmark_foreign_database_forbidden')
        if event=='open' and not isinstance(args[0],int):
            path=Path(os.fsdecode(args[0])).resolve()
            if args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):
                if path!=output and not path.is_relative_to(root):raise RuntimeError('benchmark_foreign_write_forbidden')
            elif path.suffix=='.zlib' and path.is_relative_to(root):
                counts['archive_opens']+=1;counts['archive_bytes_offered']+=path.stat().st_size
    sys.addaudithook(audit)
    return counts


def legacy_function(references,source,*,duplicate_elision=False):
    """Extract the one exact predecessor function, preserving all other nodes."""
    selected=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef)
        and node.name=='retained_reference_path')
    if duplicate_elision:
        class ElideDuplicate(ast.NodeTransformer):
            count=0
            def visit_Compare(self,node):
                expected=ast.parse('target.resolve(strict=True)!=target',mode='eval').body
                if ast.dump(node)==ast.dump(expected):
                    self.count+=1
                    return ast.parse('target!=source and target.resolve(strict=True)!=target',mode='eval').body
                return self.generic_visit(node)
        transformer=ElideDuplicate();selected=transformer.visit(selected)
        if transformer.count!=1:raise ValueError('benchmark_predecessor_duplicate_guard_mismatch')
    module=ast.fix_missing_locations(ast.Module(body=[selected],type_ignores=[]))
    namespace=dict(vars(references));exec(compile(module,'<exact-predecessor-path-proof>','exec'),namespace)
    return namespace['retained_reference_path']


def io():
    return {key:int(value) for key,value in (line.split(': ') for line in Path('/proc/thread-self/io').read_text().splitlines())}


def main(output):
    if sys.version_info[:3]!=(3,12,14):raise ValueError('benchmark_pinned_python_required')
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Scratch
    from meme_machine.runtime import candidate_history as references
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_selective_source import install
    from meme_machine.solana_scoped_retirement import ScopedRetirement
    # Read exact original source before the guard: Git itself cannot access
    # state, and the bounded native workload below remains network disabled.
    prior=subprocess.check_output(['git','show',PREDECESSOR+':meme_machine/runtime/candidate_history.py'],timeout=15)
    network_guard();os.environ['MM_OPERATION_COST_DIAGNOSTICS']='1'
    output=Path(output).resolve()
    result=dict(schema='pump-restoration-path-proof-cost-v1',scope=fixture.SCOPE,
        predecessor=PREDECESSOR,python=sys.version,sqlite=sqlite3.sqlite_version,
        predecessor_source_sha256=hashlib.sha256(prior).hexdigest(),
        candidate_source_sha256=hashlib.sha256(Path(references.__file__).read_bytes()).hexdigest(),
        fixture_roots_only_relocated=True,unmodified_original_references=True,
        opened_sqlite_inode_identity_claim=False,source_transaction_change=False,cases=[])
    with Scratch() as scratch:
        counts=audit_scope(scratch.path,output)
        legacy=scratch.path/'legacy';(legacy/'shared').mkdir(parents=True)
        corpus=fixture.capture_fixture(Path.cwd(),32,16,64,0)
        built=fixture.build_history(corpus,legacy/'shared');built['restore_at']=corpus['restore_at']
        with closing(EvidenceWriter(built['source'],clock=lambda:corpus['clock'])) as writer:
            history=install(SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity=corpus['endpoint_identity'])))
            history.clock=history.lifecycle.clock=lambda:corpus['clock']
            with closing(references.CandidateHistory(built['consumer'])) as shared:
                candidates=shared.candidates(lane='pump',event_prefix='pump_')
            for candidate in candidates[:24]:ScopedRetirement(history).restore('pump',candidate['candidate'])
        relocated=scratch.path/'aws';legacy.rename(relocated)
        built.update(source=relocated/'shared/solana-evidence.sqlite',consumer=relocated/'shared/solana-candidate-history.sqlite')
        result.update(fixture_sha256=fixture.digest(corpus),candidates=32,references=built['references'])
        with patch.object(references,'RETAINED_REFERENCE_LEGACY_ROOT',legacy),patch.object(references,'RETAINED_REFERENCE_AWS_ROOT',relocated),patch.dict(os.environ,MM_MODE='PAPER',MM_PAPER_EPOCH=references.RETAINED_REFERENCE_EPOCH,MM_STATE_ROOT=str(relocated),MM_SOLANA_EVIDENCE_PLANE_DB=str(built['source'])):
            modes=dict(original=legacy_function(references,prior),duplicate_elision=legacy_function(references,prior,duplicate_elision=True),factored_walk=references.retained_reference_path)
            for iteration in range(6):
                # Alternate ordering to avoid attributing one warmed pass to a
                # later mode. First iteration is disclosed, never discarded.
                order=list(modes) if iteration%2==0 else list(reversed(modes))
                for mode in order:
                    proof=modes[mode];metrics=dict(calls=0,cold_calls=0,cpu_seconds=0.,wall_seconds=0.,lstat_calls=0)
                    original_lstat=os.lstat;depth=[0]
                    def lstat(*args,**kwargs):
                        if depth[0]:metrics['lstat_calls']+=1
                        return original_lstat(*args,**kwargs)
                    def measured(*args,**kwargs):
                        start=time.perf_counter();cpu=time.thread_time();metrics['calls']+=1;metrics['cold_calls']+=bool(kwargs.get('cold'));depth[0]+=1
                        try:return proof(*args,**kwargs)
                        finally:
                            depth[0]-=1
                            metrics['wall_seconds']+=time.perf_counter()-start
                            metrics['cpu_seconds']+=time.thread_time()-cpu
                    # Unprofiled full restore first. The separate path profile
                    # counts syscalls with probe overhead explicitly included.
                    before=io();cpu=time.thread_time()
                    with patch.object(references,'retained_reference_path',proof):
                        restored=fixture.restore_pass(built,counts)
                    restored['reader_thread_cpu_seconds']=time.thread_time()-cpu
                    after=io();restored['reader_thread_io_delta']={k:after[k]-before[k] for k in before}
                    with patch.object(references,'retained_reference_path',measured),patch.object(os,'lstat',new=lstat):
                        profiled=fixture.restore_pass(built,counts)
                    if restored['output_sha256']!=profiled['output_sha256']:raise ValueError('benchmark_profile_economics_mismatch')
                    row=dict(mode=mode,iteration=iteration,restore=restored,path_proof_instrumented=metrics)
                    result['cases'].append(row)
                    print(json.dumps(dict(iteration=iteration,mode=mode,wall_seconds=restored['wall_seconds'],path_cpu=metrics['cpu_seconds'],path_lstat=metrics['lstat_calls'])),flush=True)
                    scratch.check()
        if len({r['restore']['output_sha256'] for r in result['cases']})!=1:raise ValueError('benchmark_economics_mismatch')
        result['network_calls']=counts['network_calls']
        output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
        scratch.check();scratch.success=True
    print(json.dumps(dict(state='COMPLETE',output=str(output))))


if __name__=='__main__':main(sys.argv[1])
