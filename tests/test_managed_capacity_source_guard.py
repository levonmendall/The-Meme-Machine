"""Complete managed-capacity successor; original economic/audit guards follow.

No operational exemption and no mocked Git source. Every changed/added runtime
byte is pinned to a committed cut, and original assertions receive authentic
immutable predecessor bytes only after the complete current cut is verified.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
BASE='83c3716aefc21d59780db64beb8681e772ac628c'
BASE_TREE='8afdc31b017c36bcd23dc6f89bf5011270c47cf1'
IMPLEMENTATION='946bd7477e5846c0b3a6eaac3f3a764aca102f17'
IMPLEMENTATION_TREE='27b49fea8cd4c09911f104725dd28e6a4b747a45'
MANIFEST=ROOT/'tests/fixtures/managed_capacity_source_delta.json'
MANIFEST_SHA256='3bbe781bb9790b4a79cb1bc7a7225935957dbbda9cf96f3c4791f2b10aa9ad5f'
MODIFIED=('meme_machine/lanes/pons/pons_survivor_runtime.py', 'meme_machine/lanes/pons/provider_topology.py')
ADDED=('meme_machine/operational/managed_capacity_evidence.py', 'meme_machine/operational/managed_capacity_workload.py', 'meme_machine/operational/managed_native_pons.py', 'meme_machine/operational/managed_native_pump.py', 'meme_machine/operational/managed_pons_survivor.py', 'meme_machine/operational/managed_pump_qualification.py')
GUARD='tests/test_native_audit_source_guard.py'
READ_GUARD='tests/test_robinhood_usd_valuation.py'
PROOF_INPUTS=('engineering/diagnostics/build_managed_capacity_source_proof.py',
    'engineering/diagnostics/managed_capacity_source_guard.template.txt')


def git(*args):
    return subprocess.check_output(['git','--no-optional-locks',*args],cwd=ROOT)


def checksum(raw):return hashlib.sha256(raw).hexdigest()


def manifest(test):
    raw=MANIFEST.read_bytes()
    test.assertEqual(checksum(raw),MANIFEST_SHA256,'complete exact managed runtime proof')
    row=json.loads(raw)
    test.assertEqual(row['schema'],'authenticated-managed-capacity-source-delta-v1')
    test.assertEqual((row['base'],row['base_tree'],row['implementation'],row['implementation_tree']),
        (BASE,BASE_TREE,IMPLEMENTATION,IMPLEMENTATION_TREE))
    test.assertEqual(set(row['files']),set(MODIFIED+ADDED))
    test.assertEqual(row['guard']['path'],GUARD)
    test.assertEqual(row['read_guard']['path'],READ_GUARD)
    test.assertEqual(set(row['proof_inputs']),set(PROOF_INPUTS))
    for path,facts in row['proof_inputs'].items():
        body=(ROOT/path).read_bytes()
        test.assertEqual((len(body),checksum(body)),(facts['bytes'],facts['sha256']),
            path+':exact reproducible proof source')
    return row


def capacity_predecessor(test,path,current):
    if path==READ_GUARD:return read_guard_predecessor(test,current)
    if path not in MODIFIED:return current
    row=manifest(test)['files'][path]
    text=type(current) is str
    test.assertIn(type(current),(bytes,str))
    raw=current.encode() if text else current
    before=git('show',BASE+':'+path)
    test.assertEqual((len(before),checksum(before)),(row['before_bytes'],row['before_sha256']))
    if raw!=before:
        test.assertEqual((len(raw),checksum(raw)),(row['after_bytes'],row['after_sha256']),
            path+':complete exact reviewed managed successor')
        test.assertEqual(raw,git('show',IMPLEMENTATION+':'+path))
        from engineering.diagnostics.build_managed_capacity_source_proof import nodes
        left,right=nodes(before),nodes(raw)
        test.assertEqual(sorted(k for k in left.keys()|right.keys() if left.get(k)!=right.get(k)),
                         row['changed_nodes'],path+':explicit changed AST nodes')
    return before.decode() if text else before


def read_guard_predecessor(test,current,*,require_successor=False):
    row=manifest(test)['read_guard']
    text=type(current) is str
    test.assertIn(type(current),(bytes,str))
    raw=current.encode() if text else current
    before=git('show',BASE+':'+READ_GUARD)
    test.assertEqual((len(before),checksum(before)),(row['before_bytes'],row['before_sha256']))
    if require_successor or raw!=before:
        test.assertEqual((len(raw),checksum(raw)),(row['after_bytes'],row['after_sha256']),
            'exact valuation read hook, every historical assertion unchanged')
        restored=raw
        for change in reversed(row['changes']):
            prior,after=change['before'].encode(),change['after'].encode()
            test.assertEqual(restored.count(after),1)
            restored=restored.replace(after,prior,1)
        test.assertEqual(restored,before,'every valuation assertion restored byte for byte')
    return before.decode() if text else before


def guard_predecessor(test,current):
    row=manifest(test)['guard']
    test.assertEqual(checksum(current),row['after_sha256'],'exact historical assertion wiring')
    restored=current
    for change in reversed(row['changes']):
        before,after=change['before'].encode(),change['after'].encode()
        test.assertEqual(restored.count(after),1)
        restored=restored.replace(after,before,1)
    test.assertEqual(checksum(restored),row['before_sha256'])
    test.assertEqual(restored,git('show',BASE+':'+GUARD),
        'every historical assertion restored byte for byte')
    return restored


def active_runtime(test):
    row=manifest(test)
    test.assertEqual(git('rev-parse',BASE+'^{tree}').decode().strip(),BASE_TREE)
    test.assertEqual(git('rev-parse',IMPLEMENTATION+'^{tree}').decode().strip(),IMPLEMENTATION_TREE)
    expected={'M\t'+p for p in MODIFIED}|{'A\t'+p for p in ADDED}
    test.assertEqual(set(git('diff','--name-status',BASE,IMPLEMENTATION,'--','meme_machine').decode().splitlines()),expected)
    test.assertEqual(git('diff','--name-only',IMPLEMENTATION,'--','meme_machine'),b'',
        'all actual current runtime bytes match the complete managed successor')
    for flags in ((),('--ignored',)):
        paths=git('ls-files','--others',*flags,'--exclude-standard','--','meme_machine').decode().splitlines()
        test.assertEqual([p for p in paths if '__pycache__' not in Path(p).parts and not p.endswith('.pyc')],[])
    for path,facts in row['files'].items():
        body=(ROOT/path).read_bytes()
        test.assertEqual((len(body),checksum(body)),(facts['after_bytes'],facts['after_sha256']),path)
        test.assertEqual(body,git('show',IMPLEMENTATION+':'+path))
        if path in MODIFIED:capacity_predecessor(test,path,body)
    guard_predecessor(test,(ROOT/GUARD).read_bytes())
    read_guard_predecessor(test,(ROOT/READ_GUARD).read_bytes(),require_successor=True)
    return row


def capacity_active_delta(test,actual,old_implementation):
    active_runtime(test)
    test.assertEqual(actual,git('diff','--name-only',old_implementation,IMPLEMENTATION,'--','meme_machine'),
        'original guard must supply the genuine complete current runtime delta')
    return git('diff','--name-only',old_implementation,BASE,'--','meme_machine')


def capacity_native_delta(test,actual,old_implementation):
    active_runtime(test)
    historical=git('diff','--name-only',old_implementation,BASE,'--','meme_machine')
    current=git('diff','--name-only',old_implementation,IMPLEMENTATION,'--','meme_machine')
    # The original guard's own negative tests also call its historical API.
    # Both accepted inputs are exact real Git queries; no unknown path is lost.
    test.assertIn(actual,(historical,current))
    return historical


class ManagedCapacitySourceGuard(unittest.TestCase):
    def test_complete_current_runtime_and_every_original_assertion_are_pinned(self):
        active_runtime(self)

    def test_unknown_modified_and_added_runtime_bytes_cannot_pass(self):
        row=manifest(self)
        for path in MODIFIED:
            body=(ROOT/path).read_bytes()
            with self.subTest(path=path),self.assertRaises(AssertionError):
                capacity_predecessor(self,path,body+b'\n# unreviewed runtime\n')
        read=Path.read_bytes
        for path in ADDED:
            with self.subTest(path=path),patch.object(Path,'read_bytes',
                lambda p: b'changed' if p==ROOT/path else read(p)),self.assertRaises(AssertionError):
                active_runtime(self)

    def test_economic_sizing_and_admission_delta_cannot_be_partially_reversed(self):
        for path in MODIFIED:
            before=git('show',BASE+':'+path)
            body=(ROOT/path).read_bytes()
            self.assertEqual(capacity_predecessor(self,path,before),before)
            self.assertEqual(capacity_predecessor(self,path,body.decode()),before.decode())
            with self.subTest(path=path),self.assertRaises(AssertionError):
                capacity_predecessor(self,path,body[:-1])

    def test_unlisted_source_and_unknown_manifest_are_rejected(self):
        original=git
        def extra(*args):
            if args==('diff','--name-only',IMPLEMENTATION,'--','meme_machine'):
                return b'meme_machine/unlisted.py\n'
            return original(*args)
        with patch(__name__+'.git',side_effect=extra),self.assertRaises(AssertionError):
            active_runtime(self)
        read=Path.read_bytes
        with patch.object(Path,'read_bytes',lambda p:b'{}' if p==MANIFEST else read(p)),self.assertRaises(AssertionError):
            manifest(self)

    def test_original_assertion_change_cannot_hide_in_read_dispatch(self):
        body=(ROOT/GUARD).read_bytes()
        guard_predecessor(self,body)
        for bad in (body+b'\n',body.replace(b'assertEqual',b'assertNotEqual',1)):
            with self.assertRaises(AssertionError):guard_predecessor(self,bad)

    def test_valuation_read_hook_cannot_change_original_assertions_or_source(self):
        body=(ROOT/READ_GUARD).read_bytes()
        before=git('show',BASE+':'+READ_GUARD)
        self.assertEqual(read_guard_predecessor(self,body,require_successor=True),before)
        self.assertEqual(capacity_predecessor(self,READ_GUARD,before),before)
        self.assertEqual(capacity_predecessor(self,READ_GUARD,body.decode()),before.decode())
        for bad in (body+b'\n',body.replace(b'assertEqual',b'assertNotEqual',1),body[:-1]):
            with self.assertRaises(AssertionError):capacity_predecessor(self,READ_GUARD,bad)
        with self.assertRaises(AssertionError):
            read_guard_predecessor(self,before,require_successor=True)
