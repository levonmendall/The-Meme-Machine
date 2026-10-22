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
IMPLEMENTATION='58daaa5afef66169062b74ffe617cfeaa9975c12'
IMPLEMENTATION_TREE='270b9b312de63d9bc082c1a6cf838da683640121'
MANIFEST=ROOT/'tests/fixtures/managed_capacity_source_delta.json'
MANIFEST_SHA256='f788ebc579985a953a5dea7fae115aeb305e14558e876e5874b177a86060f50b'
MODIFIED=('meme_machine/lanes/pons/pons_survivor_runtime.py', 'meme_machine/lanes/pons/provider_topology.py', 'meme_machine/runtime/evidence_worker.py', 'meme_machine/shared_capital/adapter.py', 'meme_machine/solana_candidate_join.py', 'meme_machine/solana_candidate_lifecycle.py', 'meme_machine/solana_economic_preparation.py', 'meme_machine/solana_evidence_control.py', 'meme_machine/solana_evidence_service.py', 'meme_machine/solana_history_archive.py', 'meme_machine/solana_history_delivery.py', 'meme_machine/solana_history_notifications.py', 'meme_machine/solana_scoped_retirement.py', 'meme_machine/solana_selective_history.py', 'meme_machine/solana_selective_source.py')
ADDED=('meme_machine/operational/managed_capacity_evidence.py', 'meme_machine/operational/managed_capacity_workload.py', 'meme_machine/operational/managed_native_pons.py', 'meme_machine/operational/managed_native_pump.py', 'meme_machine/operational/managed_pons_survivor.py', 'meme_machine/operational/managed_pump_qualification.py', 'meme_machine/operational/managed_qualification_replay.py', 'meme_machine/solana_derived_fanout.py', 'meme_machine/solana_preparation_pool.py', 'meme_machine/solana_stream_log_repair.py')
TEST_CALLERS={'tests/test_solana_history_separation.py': {'before_bytes': 80082, 'before_sha256': 'e7f2a1552e50eef898b4bf8920b0d40a21a67af2849ed9a79aaca60874969608', 'after_bytes': 91749, 'after_sha256': '8fabed60a03b155d12b666e64bff9430c24089ea346dbaf96daa613393fad8c6', 'changed_nodes': ['CaptureActorTests.__layout__', 'CaptureActorTests.__statement_0', 'CaptureActorTests.__statement_1', 'CaptureActorTests.actor', 'CaptureActorTests.test_corrupt_receipt_and_new_generation_never_advance_actor_ack', 'CaptureActorTests.test_delayed_revision_reopens_behind_cursor_without_resetting_active_tail', 'CaptureActorTests.test_empty_refresh_feedback_cannot_clear_rearmed_request_and_own_ack_does_not_stale_eof', 'CaptureActorTests.test_reader_snapshot_is_coherent_and_closed_before_consumer_write_and_fresh_ack', 'CaptureActorTests.test_refresh_eof_rejection_finishes_bounded_horizon_then_revisits_behind_cursor', 'CaptureActorTests.test_replacement_during_read_fails_closed_and_does_not_pin_reader', '__statement_13', '__statement_14', '__statement_15', '__statement_16', '__statement_17', '__statement_18', '__statement_19', '__statement_20', '__statement_21']}}
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
    test.assertEqual(row['test_callers'],TEST_CALLERS)
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
    if path in TEST_CALLERS:return caller_predecessor(test,path,current)
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


def caller_predecessor(test,path,current,*,require_successor=False):
    test.assertIn(path,TEST_CALLERS,'only the separately cataloged exact test caller')
    row=manifest(test)['test_callers'][path]
    text=type(current) is str
    test.assertIn(type(current),(bytes,str))
    raw=current.encode() if text else current
    before=git('show',BASE+':'+path)
    test.assertEqual((len(before),checksum(before)),(row['before_bytes'],row['before_sha256']))
    if require_successor or raw!=before:
        test.assertEqual((len(raw),checksum(raw)),(row['after_bytes'],row['after_sha256']),
            path+':complete exact reviewed test caller')
        test.assertEqual(raw,git('show',IMPLEMENTATION+':'+path))
        from engineering.diagnostics.build_managed_capacity_source_proof import nodes
        left,right=nodes(before),nodes(raw)
        test.assertEqual(sorted(k for k in left.keys()|right.keys() if left.get(k)!=right.get(k)),
                         row['changed_nodes'],path+':explicit test caller AST delta')
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
    for path in TEST_CALLERS:
        caller_predecessor(test,path,(ROOT/path).read_bytes(),require_successor=True)
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

    def test_exact_external_test_caller_preserves_every_original_method_and_rejects_unknown_bytes(self):
        from engineering.diagnostics.build_managed_capacity_source_proof import nodes
        self.assertEqual(set(TEST_CALLERS),{'tests/test_solana_history_separation.py'})
        for path in TEST_CALLERS:
            before=git('show',BASE+':'+path);body=(ROOT/path).read_bytes()
            self.assertEqual(caller_predecessor(self,path,body,require_successor=True),before)
            self.assertEqual(capacity_predecessor(self,path,before),before)
            self.assertEqual(capacity_predecessor(self,path,body.decode()),before.decode())
            self.assertEqual(capacity_predecessor(self,path,before.decode()),before.decode())
            left,right=nodes(before),nodes(body)
            methods={name:value for name,value in left.items() if '.' in name
                and not name.endswith('.__layout__') and '__statement_' not in name}
            self.assertTrue(methods)
            for name,value in methods.items():
                self.assertEqual(right.get(name),value,path+':original method '+name)
            for bad in (b'',body[:-1],body+b'\n# unknown caller bytes\n',
                    body.replace(b'assertEqual',b'assertNotEqual',1),(ROOT/GUARD).read_bytes()):
                with self.subTest(path=path),self.assertRaises(AssertionError):
                    capacity_predecessor(self,path,bad)
            with self.assertRaises(AssertionError):
                caller_predecessor(self,path,before,require_successor=True)
        with self.assertRaises(AssertionError):
            caller_predecessor(self,'tests/unknown_external_caller.py',b'unknown')
