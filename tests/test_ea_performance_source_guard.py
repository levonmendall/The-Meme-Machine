"""Exact performance-only successor; the unchanged EA and strategy guards follow."""
from tests.test_native_audit_source_guard import audit_predecessor, audit_predecessor_runtime_delta
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
BASE='b10b7a13a0e872038018a43816e2ff0f75c93e55'
BASE_TREE='4d4493fc3b07e71ab57ea64098463028f999d03d'
IMPLEMENTATION='6eb8ab1ba1702224c1354c570db4f87aeb7b5ccd'
IMPLEMENTATION_TREE='70319a41b9f766c9608153d8c6057a4c7fb2fbca'
MANIFEST=ROOT/'tests/fixtures/ea_performance_source_delta.json'
MANIFEST_SHA256='9b99d04abfa913311a0c7dc771390908a3a60e4c36f88c4f241d6ba4fc0a8e50'
INNER_MANIFEST='tests/fixtures/operational_candidate_source_delta.json'
INNER_MANIFEST_SHA256='f1982ceef86d7acab5666c66bf951651d0f565dfd765300b691195b372f1b79c'
PATHS=('meme_machine/runtime/candidate_restore_reads.py',
    'meme_machine/runtime/operation_costs.py','meme_machine/runtime/robinhood/plane.py')
GUARDS={'tests/test_operational_candidate_source_guard.py': '93e9bfa02921ba52b3c2cdc0466a1fa430f9db4ba887e44d892ea6001a7724be', 'tests/test_pump_restore_source_guard.py': 'f8a998706fa861a53bb1552314daa21e662a8ac6c175294ac3a9661283ef4261', 'tests/test_robinhood_usd_valuation.py': '39ac7f9a25626f2af399fe73dd764730ef21ce9618fca52319fa41249667e65b'}
READS={
    'tests/test_operational_candidate_source_guard.py':(
        ('test_sixteen_complete_sources_reverse_exactly_to_approved_780','performance_source','relative'),
        ('test_original_guards_reverse_exactly_and_only_active_read_dispatch_changes','performance_guard_source','relative'),
        ('test_unknown_truncated_or_partially_reversed_source_never_passes','performance_source','relative'),
        ('test_protection_expiry_scope_raw_writes_rollback_and_borrow_guards_cannot_be_weakened','performance_source','relative')),
    'tests/test_pump_restore_source_guard.py':(
        ('authenticated_helper','performance_source','HELPER'),
        ('test_legacy_guard_file_reverses_only_ten_active_reads_and_one_import','performance_guard_source',"row['path']"),
        ('test_complete_helper_pin_refuses_any_budget_path_hash_or_owner_mutation','performance_source','HELPER')),
    'tests/test_robinhood_usd_valuation.py':(
        ('guarded_source','performance_source','relative'),
        ('test_publication_accounting_turn_preserves_durable_delta_cancellation_and_passive_pump_costs','performance_source','relative'),
        ('test_source_recorder_publication_reverses_only_exact_diagnostic_transport_and_test_read','performance_guard_source','relative')),
}
UNCHANGED_EXTERNAL_CALLERS=(
    'tests/test_extended_survivor_hold_research.py','tests/test_robinhood_scout.py',
    'tests/test_forward_survivor.py','tests/test_long_duration_positions.py',
    'tests/test_solana_history_separation.py','tests/test_shared_capital_strategy.py',
    'tests/test_pons_owner_admission.py')


def manifest(test):
    raw=MANIFEST.read_bytes()
    test.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256,'exact performance successor proof')
    value=json.loads(raw)
    test.assertEqual(value['schema'],'authenticated-ea-performance-source-delta-v1')
    test.assertEqual((value['base'],value['base_tree'],value['implementation'],value['implementation_tree']),
        (BASE,BASE_TREE,IMPLEMENTATION,IMPLEMENTATION_TREE))
    test.assertEqual(set(value['files']),set(PATHS))
    test.assertEqual(set(value['guards']),set(GUARDS))
    test.assertEqual(value['inner_manifest_sha256'],INNER_MANIFEST_SHA256)
    return value


def _inverse(test,relative,current,record):
    text=type(current) is str
    test.assertIn(type(current),(str,bytes))
    raw=current.encode() if text else current
    checksum=hashlib.sha256(raw).hexdigest()
    if checksum==record['before_sha256']:
        test.assertEqual(len(raw),record['before_bytes']);return current
    test.assertEqual(checksum,record['after_sha256'],relative+':complete reviewed performance successor')
    test.assertEqual(len(raw),record['after_bytes'])
    restored=raw
    for change in record['changes']:
        before,after=(change[key].encode() for key in ('before','after'))
        test.assertTrue(after)
        test.assertEqual(restored.count(after),1,relative+':one exact reversible delta')
        restored=restored.replace(after,before,1)
    test.assertEqual(len(restored),record['before_bytes'])
    test.assertEqual(hashlib.sha256(restored).hexdigest(),record['before_sha256'])
    from tests.test_robinhood_usd_valuation import rally_delta
    test.assertEqual(rally_delta(restored,raw),{key:record[key] for key in ('nodes','layouts')})
    return restored.decode() if text else restored


def performance_source(test,relative,current):
    """Normalize only fixed complete active sources before the unchanged EA16."""
    if relative not in PATHS:return current
    return _inverse(test,relative,current,manifest(test)['files'][relative])


def performance_guard_source(test,relative,current):
    """Restore three complete old guard files before their old self-checks."""
    test.assertIn(relative,GUARDS)
    return _inverse(test,relative,current,manifest(test)['guards'][relative])


def read_hooks(raw):
    found=[]
    def walk(node,owner):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):owner=owner+'/'+node.name
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in (
                'performance_source','performance_guard_source'):
            found.append(dict(caller=owner,call=ast.dump(node)))
        for child in ast.iter_child_nodes(node):walk(child,owner)
    walk(ast.parse(raw),'module')
    return sorted(found,key=lambda row:(row['caller'],row['call']))


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


class EAPerformanceSourceGuardTests(unittest.TestCase):
    def test_complete_three_file_frozen_and_active_runtime_delta(self):
        value=manifest(self)
        changed=git('diff','--name-status',BASE,IMPLEMENTATION,'--','meme_machine').decode().splitlines()
        self.assertEqual(set(changed),{'M\t'+path for path in PATHS})
        self.assertEqual(git('rev-parse',BASE+'^{tree}').decode().strip(),BASE_TREE)
        self.assertEqual(git('rev-parse',IMPLEMENTATION+'^{tree}').decode().strip(),IMPLEMENTATION_TREE)
        self.assertEqual(audit_predecessor_runtime_delta(self,git('diff','--name-only',IMPLEMENTATION,'--','meme_machine')),b'',
            'no active runtime source differs from the complete frozen candidate')
        for option in ((),('--ignored',)):
            extra=git('ls-files','--others',*option,'--exclude-standard','--','meme_machine').decode().splitlines()
            self.assertEqual([path for path in extra if '__pycache__' not in Path(path).parts and not path.endswith('.pyc')],[],
                'new unlisted runtime inputs are not part of this exact successor')
        for path,row in value['files'].items():
            current=audit_predecessor(self,path,(ROOT/path).read_bytes())
            self.assertEqual(current,git('show',IMPLEMENTATION+':'+path))
            before=performance_source(self,path,current)
            self.assertEqual(before,git('show',BASE+':'+path))
            self.assertEqual(performance_source(self,path,before),before)
            self.assertEqual(performance_source(self,path,current.decode()),before.decode())

    def test_changed_deleted_and_unlisted_active_inputs_are_rejected(self):
        original=git
        frozen=('diff','--name-status',BASE,IMPLEMENTATION,'--','meme_machine')
        active=('diff','--name-only',IMPLEMENTATION,'--','meme_machine')
        untracked=('ls-files','--others','--exclude-standard','--','meme_machine')
        ignored=('ls-files','--others','--ignored','--exclude-standard','--','meme_machine')
        for command,reply in ((frozen,b'M\tmeme_machine/unreviewed.py\n'),
                (frozen,b'D\t'+PATHS[0].encode()+b'\n'),(active,PATHS[0].encode()+b'\n'),
                (untracked,b'meme_machine/unreviewed.py\n'),
                (ignored,b'meme_machine/unreviewed.json\n')):
            def supplied(*args):return reply if args==command else original(*args)
            with self.subTest(command=command,reply=reply),patch(__name__+'.git',side_effect=supplied),\
                    self.assertRaises(AssertionError):
                self.test_complete_three_file_frozen_and_active_runtime_delta()

    def test_ten_active_read_wrappers_restore_three_whole_original_guard_files(self):
        value=manifest(self);total=0
        declaration="'tests.test_ea_performance_source_guard',"
        for path in ('operational/tests.py','.github/workflows/ci.yml'):
            self.assertEqual((ROOT/path).read_text().count(declaration),1)
        for path,expected in GUARDS.items():
            current=audit_predecessor(self,path,(ROOT/path).read_bytes());row=value['guards'][path]
            self.assertEqual(row['before_sha256'],expected)
            before=performance_guard_source(self,path,current)
            self.assertEqual(before,git('show',BASE+':'+path),
                'all old constants, assertions, predecessor bodies and mutation calls remain exact')
            self.assertEqual(read_hooks(current),row['fixed_read_hooks'])
            actual=[]
            tree=ast.parse(current)
            for node in ast.walk(tree):
                if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
                for call in ast.walk(node):
                    if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Name) or call.func.id not in (
                            'performance_source','performance_guard_source'):continue
                    self.assertEqual(len(call.args),3);self.assertFalse(call.keywords)
                    raw=call.args[2]
                    self.assertIsInstance(raw,ast.Call);self.assertIsInstance(raw.func,ast.Attribute)
                    self.assertEqual(raw.func.attr,'read_bytes');self.assertFalse(raw.args);self.assertFalse(raw.keywords)
                    expression=ast.unparse(call.args[1])
                    self.assertEqual(ast.dump(raw.func.value),ast.dump(ast.parse('ROOT / '+expression,mode='eval').body))
                    actual.append((node.name,call.func.id,expression))
            self.assertEqual(sorted(actual),sorted(READS[path]));total+=len(actual)
            for changed in (current+b'\n# unknown guard bytes\n',current.replace(b'assertEqual',b'assertNotEqual',1)):
                with self.subTest(path=path),self.assertRaises(AssertionError):
                    performance_guard_source(self,path,changed)
        self.assertEqual(total,10)

    def test_immutable_inner_proof_and_original_exported_predecessor_bodies(self):
        self.assertEqual(hashlib.sha256(audit_predecessor(self,INNER_MANIFEST,(ROOT/INNER_MANIFEST).read_bytes())).hexdigest(),INNER_MANIFEST_SHA256)
        for path,names in {
                'tests/test_operational_candidate_source_guard.py':('candidate_source_predecessor','original_guard_source','_inverse'),
                'tests/test_pump_restore_source_guard.py':('pump_restore_predecessor',),
                'tests/test_robinhood_usd_valuation.py':('opportunity_predecessor','assert_holding_delta','rally_delta')}.items():
            before=ast.parse(git('show',BASE+':'+path));after=ast.parse(audit_predecessor(self,path,(ROOT/path).read_bytes()))
            for name in names:
                nodes=[next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name)
                    for tree in (before,after)]
                self.assertEqual(ast.dump(nodes[0]),ast.dump(nodes[1]),path+':'+name)
        # The earlier complete caller census found these seven raw strategy
        # boundaries. Their files and selected strategies are unchanged here;
        # no performance normalization belongs in mutation/intermediate calls.
        for path in UNCHANGED_EXTERNAL_CALLERS:
            self.assertEqual(audit_predecessor(self,path,(ROOT/path).read_bytes()),git('show',BASE+':'+path))
            self.assertEqual(git('show',IMPLEMENTATION+':'+path),git('show',BASE+':'+path))

    def test_unknown_truncated_partial_and_crossed_sources_fail_closed(self):
        for path,row in manifest(self)['files'].items():
            current=audit_predecessor(self,path,(ROOT/path).read_bytes())
            changed=[b'',current+b'\n# unknown runtime bytes\n']
            for hunk in row['changes']:
                partial=current.replace(hunk['after'].encode(),hunk['before'].encode(),1)
                if hashlib.sha256(partial).hexdigest()!=row['before_sha256']:changed.append(partial)
            for raw in changed:
                with self.subTest(path=path),self.assertRaises(AssertionError):performance_source(self,path,raw)
            for other in PATHS:
                if other!=path:
                    with self.subTest(path=path,other=other),self.assertRaises(AssertionError):
                        performance_source(self,path,audit_predecessor(self,other,(ROOT/other).read_bytes()))
        self.assertEqual(performance_source(self,'unrelated/source.py',b'unchanged'),b'unchanged')

    def test_manifest_tampering_never_becomes_a_source_exemption(self):
        original=MANIFEST.read_bytes();read=Path.read_bytes
        for changed in (original+b'\n',b'{}',original.replace(BASE.encode(),b'f'*40,1)):
            with patch.object(Path,'read_bytes',new=lambda path:changed if path==MANIFEST else read(path)),\
                    self.assertRaises(AssertionError):
                performance_source(self,PATHS[0],audit_predecessor(self,PATHS[0],(ROOT/PATHS[0]).read_bytes()))

