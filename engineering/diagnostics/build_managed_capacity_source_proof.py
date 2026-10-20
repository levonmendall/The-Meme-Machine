"""Build an exact outer source proof without replacing historical assertions.

Offline only. The implementation is a committed runtime cut; the new guard
authenticates every changed/added byte and returns genuine immutable predecessor
sources to the original economic/audit guards. No provider or host authority.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = '83c3716aefc21d59780db64beb8681e772ac628c'
GUARD = 'tests/test_native_audit_source_guard.py'
READ_GUARD = 'tests/test_robinhood_usd_valuation.py'
PROOF_INPUTS = ('engineering/diagnostics/build_managed_capacity_source_proof.py',
                'engineering/diagnostics/managed_capacity_source_guard.template.txt')


def git(*args):
    return subprocess.check_output(['git', '--no-optional-locks', *args], cwd=ROOT)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def nodes(raw):
    tree = ast.parse(raw)
    found = {}
    def walk(parent, prefix=''):
        for index, node in enumerate(parent.body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                if isinstance(node, ast.ClassDef):
                    # Method layout and all nonmethod class statements remain
                    # explicit; copying a method cannot conceal a sibling edit.
                    found[name + '.__layout__'] = ast.dump(ast.ClassDef(name=node.name,
                        bases=node.bases, keywords=node.keywords,
                        body=[ast.Pass() if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                              else n for n in node.body], decorator_list=node.decorator_list,
                        type_params=node.type_params))
                    walk(node, name + '.')
                else:
                    found[name] = ast.dump(node)
            else:
                found[prefix + '__statement_%d' % index] = ast.dump(node)
    walk(tree)
    return found


def main():
    implementation = sys.argv[1]
    if git('rev-parse', implementation).decode().strip() != implementation:
        raise ValueError('exact_runtime_cut_required')
    if git('diff', implementation, '--', 'meme_machine').strip():
        raise ValueError('commit_runtime_before_proof')
    files = {}
    modified = []
    added = []
    for raw in git('diff', '--name-status', BASE, implementation, '--', 'meme_machine').decode().splitlines():
        status, name = raw.split('\t')
        if status not in ('A', 'M'):
            raise ValueError('unexpected_runtime_removal_or_rename')
        after = git('show', implementation + ':' + name)
        row = dict(status=status, after_bytes=len(after), after_sha256=sha(after))
        if status == 'M':
            before = git('show', BASE + ':' + name)
            left, right = nodes(before), nodes(after)
            row.update(before_bytes=len(before), before_sha256=sha(before),
                changed_nodes=sorted(k for k in left.keys() | right.keys() if left.get(k) != right.get(k)))
            modified.append(name)
        else:
            added.append(name)
        files[name] = row
    before_guard = git('show', BASE + ':' + GUARD)
    changes = [
        (b'import ast\n', b'from tests.test_managed_capacity_source_guard import (capacity_predecessor, capacity_active_delta, capacity_native_delta)\nimport ast\n'),
        (b'    if path not in FILES+GUARDS:return current\n',
         b'    current=capacity_predecessor(test,path,current)\n    if path not in FILES+GUARDS:return current\n'),
        (b"test.assertEqual(git('diff','--name-only',IMPLEMENTATION,'--','meme_machine'),b'',",
         b"test.assertEqual(capacity_active_delta(test,git('diff','--name-only',IMPLEMENTATION,'--','meme_machine'),IMPLEMENTATION),b'',"),
        (b'    active_runtime(test)\n    test.assertEqual(actual_delta,',
         b'    active_runtime(test)\n    actual_delta=capacity_native_delta(test,actual_delta,OLD_IMPLEMENTATION)\n    test.assertEqual(actual_delta,'),
        (b"    for path,row in value['guards'].items():\n        body=(ROOT/path).read_bytes()\n",
         b"    for path,row in value['guards'].items():\n        body=capacity_predecessor(test,path,(ROOT/path).read_bytes())\n"),
        (b"        for path,row in value['guards'].items():\n            body=(ROOT/path).read_bytes()\n",
         b"        for path,row in value['guards'].items():\n            body=capacity_predecessor(self,path,(ROOT/path).read_bytes())\n"),
    ]
    after_guard = before_guard
    for before, after in changes:
        if after_guard.count(before) != 1:
            raise ValueError('exact_guard_read_hook_required')
        after_guard = after_guard.replace(before, after, 1)
    (ROOT / GUARD).write_bytes(after_guard)
    before_read_guard = git('show', BASE + ':' + READ_GUARD)
    read_changes = [
        (b"            source=publication_accounting_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))\n",
         b"            source=publication_accounting_predecessor(self,relative,pump_restore_predecessor(self,relative,audit_predecessor(self,relative,(ROOT/relative).read_bytes())))\n"),
    ]
    after_read_guard = before_read_guard
    for before, after in read_changes:
        if after_read_guard.count(before) != 1:
            raise ValueError('exact_valuation_read_hook_required')
        after_read_guard = after_read_guard.replace(before, after, 1)
    (ROOT / READ_GUARD).write_bytes(after_read_guard)
    proof = dict(schema='authenticated-managed-capacity-source-delta-v1', base=BASE,
        base_tree=git('rev-parse', BASE + '^{tree}').decode().strip(),
        implementation=implementation,
        implementation_tree=git('rev-parse', implementation + '^{tree}').decode().strip(), files=files,
        guard=dict(path=GUARD, before_sha256=sha(before_guard), after_sha256=sha(after_guard),
            changes=[dict(before=a.decode(), after=b.decode()) for a, b in changes]),
        read_guard=dict(path=READ_GUARD,
            before_bytes=len(before_read_guard), before_sha256=sha(before_read_guard),
            after_bytes=len(after_read_guard), after_sha256=sha(after_read_guard),
            changes=[dict(before=a.decode(), after=b.decode()) for a, b in read_changes]),
        proof_inputs={p:dict(bytes=len((ROOT/p).read_bytes()), sha256=sha((ROOT/p).read_bytes()))
                      for p in PROOF_INPUTS})
    body=(json.dumps(proof, sort_keys=True, indent=2) + '\n').encode()
    (ROOT/'tests/fixtures/managed_capacity_source_delta.json').write_bytes(body)
    template=(ROOT/PROOF_INPUTS[1]).read_text()
    source=template.replace('@@MANIFEST_SHA256@@', sha(body)).replace(
        '@@IMPLEMENTATION@@', implementation).replace('@@IMPLEMENTATION_TREE@@',
        proof['implementation_tree']).replace('@@MODIFIED@@', repr(tuple(modified))).replace(
        '@@ADDED@@', repr(tuple(added)))
    if '@@' in source:
        raise ValueError('unfilled_source_proof')
    (ROOT/'tests/test_managed_capacity_source_guard.py').write_text(source)
    print(json.dumps(dict(status='EXACT_MANAGED_SOURCE_PROOF_BUILT', implementation=implementation,
                          files=len(files), manifest_sha256=sha(body))))


if __name__ == '__main__':
    main()
