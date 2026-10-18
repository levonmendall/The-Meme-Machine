"""Reproduce the exact, offline 780 -> frozen integrated candidate source pin.

No provider/state access. This writes only the declared test fixture and updates
its digest in the test helper; the original assertions are not generated/edited.
"""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
BASE='780f4015efd9fba528e97223f8e8e3b1a7322e12'
IMPLEMENTATION='4b1c54a508e82e5fb7a975dc75362081cdcf77e5'
PATHS=('engineering/diagnostics/current_combined_observation_20261014.py',
       'meme_machine/lanes/pons/pons_selective_cohort.py','meme_machine/operational/lane.py',
       'meme_machine/runtime/candidate_restore_reads.py','meme_machine/runtime/operation_costs.py',
       'meme_machine/runtime/robinhood/plane.py','meme_machine/runtime/robinhood/pons.py',
       'meme_machine/runtime/status.py','meme_machine/runtime/survivor_history.py',
       'meme_machine/solana_source_drain.py')
GUARDS=('tests/test_pump_restore_source_guard.py','tests/test_robinhood_usd_valuation.py')


def git(*args):
    return subprocess.run(['git',*args],cwd=ROOT,capture_output=True,check=True).stdout


def digest(raw):return hashlib.sha256(raw).hexdigest()


def inverse_record(before,after):
    from tests.test_robinhood_usd_valuation import rally_delta
    a,b=before.decode().splitlines(keepends=True),after.decode().splitlines(keepends=True)
    changes=[]
    for group in difflib.SequenceMatcher(None,a,b,autojunk=False).get_grouped_opcodes(5):
        first,last=group[0],group[-1]
        prior=''.join(a[first[1]:last[2]]);successor=''.join(b[first[3]:last[4]])
        if not successor or after.count(successor.encode())!=1:raise ValueError('source_delta_not_unique')
        changes.append(dict(before=prior,after=successor))
    restored=after
    for change in changes:
        if restored.count(change['after'].encode())!=1:raise ValueError('source_inverse_not_unique')
        restored=restored.replace(change['after'].encode(),change['before'].encode(),1)
    if restored!=before:raise ValueError('source_inverse_incomplete')
    return dict(before_sha256=digest(before),after_sha256=digest(after),
        before_bytes=len(before),after_bytes=len(after),changes=changes,**rally_delta(before,after))


def calls(raw):
    """Fixed named callers; no line-number instability or implicit read patch."""
    found=[]
    def walk(node,owner):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):owner=owner+'/'+node.name
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in (
                'candidate_source_predecessor','original_guard_source','pump_restore_predecessor'):
            found.append(dict(caller=owner,call=ast.dump(node)))
        for child in ast.iter_child_nodes(node):walk(child,owner)
    walk(ast.parse(raw),'module')
    return sorted(found,key=lambda row:(row['caller'],row['call']))


def main():
    sys.path.insert(0,str(ROOT))
    actual=set(git('diff','--name-only',BASE,IMPLEMENTATION,'--','meme_machine',PATHS[0]).decode().splitlines())
    if actual!=set(PATHS):raise ValueError('changed_runtime_census')
    value=dict(schema='authenticated-operational-candidate-source-delta-v1',base=BASE,
        base_tree=git('rev-parse',BASE+'^{tree}').decode().strip(),implementation=IMPLEMENTATION,
        implementation_tree=git('rev-parse',IMPLEMENTATION+'^{tree}').decode().strip(),files={},guards={})
    for relative in PATHS:
        before=git('show',BASE+':'+relative);after=git('show',IMPLEMENTATION+':'+relative)
        if (ROOT/relative).read_bytes()!=after:raise ValueError('working_runtime_not_frozen')
        value['files'][relative]=inverse_record(before,after)
    for relative in GUARDS:
        before=git('show',IMPLEMENTATION+':'+relative);after=(ROOT/relative).read_bytes()
        value['guards'][relative]=dict(inverse_record(before,after),fixed_read_hooks=calls(after))
    path=ROOT/'tests/fixtures/operational_candidate_source_delta.json'
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();path.write_bytes(raw)
    helper=ROOT/'tests/test_operational_candidate_source_guard.py';source=helper.read_text()
    tree=ast.parse(source);node=next(row for row in tree.body if isinstance(row,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='MANIFEST_SHA256' for target in row.targets))
    lines=source.splitlines(keepends=True);lines[node.lineno-1]="MANIFEST_SHA256='"+digest(raw)+"'\n"
    helper.write_text(''.join(lines))
    print(json.dumps(dict(manifest_sha256=digest(raw),manifest_bytes=len(raw),runtime_files=len(PATHS))))


if __name__=='__main__':main()
