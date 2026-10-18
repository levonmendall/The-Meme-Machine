"""Reproduce only the fixed b10 -> frozen three-file performance proof.

This offline test-fixture builder grants no source, financial or runtime
authority. It preserves the immutable inner EA16 proof and old assertions.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def main():
    sys.path.insert(0,str(ROOT))
    from tests import test_ea_performance_source_guard as guard
    from engineering.diagnostics.build_operational_candidate_source_proof import inverse_record
    changed=git('diff','--name-status',guard.BASE,guard.IMPLEMENTATION,'--','meme_machine').decode().splitlines()
    if set(changed)!={'M\t'+path for path in guard.PATHS}:raise ValueError('performance_runtime_census')
    if hashlib.sha256((ROOT/guard.INNER_MANIFEST).read_bytes()).hexdigest()!=guard.INNER_MANIFEST_SHA256:
        raise ValueError('performance_inner_proof_changed')
    value=dict(schema='authenticated-ea-performance-source-delta-v1',
        base=guard.BASE,base_tree=git('rev-parse',guard.BASE+'^{tree}').decode().strip(),
        implementation=guard.IMPLEMENTATION,
        implementation_tree=git('rev-parse',guard.IMPLEMENTATION+'^{tree}').decode().strip(),
        inner_manifest_sha256=guard.INNER_MANIFEST_SHA256,files={},guards={})
    for path in guard.PATHS:
        before=git('show',guard.BASE+':'+path);after=git('show',guard.IMPLEMENTATION+':'+path)
        if (ROOT/path).read_bytes()!=after:raise ValueError('performance_runtime_not_frozen')
        value['files'][path]=inverse_record(before,after)
    for path,expected in guard.GUARDS.items():
        before=git('show',guard.BASE+':'+path);after=(ROOT/path).read_bytes()
        if hashlib.sha256(before).hexdigest()!=expected:raise ValueError('performance_original_guard')
        value['guards'][path]=dict(inverse_record(before,after),fixed_read_hooks=guard.read_hooks(after))
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    guard.MANIFEST.write_bytes(raw)
    path=ROOT/'tests/test_ea_performance_source_guard.py';source=path.read_text();tree=ast.parse(source)
    node=next(row for row in tree.body if isinstance(row,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='MANIFEST_SHA256' for target in row.targets))
    lines=source.splitlines(keepends=True);lines[node.lineno-1]="MANIFEST_SHA256='"+hashlib.sha256(raw).hexdigest()+"'\n"
    path.write_text(''.join(lines))
    print(json.dumps(dict(manifest_sha256=hashlib.sha256(raw).hexdigest(),manifest_bytes=len(raw),
        runtime_sources=len(value['files']),whole_original_guards=len(value['guards']))))


if __name__=='__main__':main()
