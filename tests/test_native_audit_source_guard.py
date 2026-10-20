"""Exact stable-audit successor; historical source/economic guards still run.

This test-only source view has no operational or financial authority.  The
complete current checkout is checked separately from its exact 0e9 predecessor.
"""
from tests.test_managed_capacity_source_guard import (capacity_predecessor, capacity_active_delta, capacity_native_delta)
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
BASE='0e9a0ffe1912c28258735909ebce933803585556'
BASE_TREE='8646cdcd1de820e909090f0c1fd899e12dffe9ea'
IMPLEMENTATION='c0190478fcfe64e4db96c54189ec470cdb5ec686'
IMPLEMENTATION_TREE='041d380654e06e41fb66f2cffd789994350195c6'
MANIFEST=ROOT/'tests/fixtures/native_audit_source_delta.json'
MANIFEST_SHA256='0c4fe23635a33644c0d0dc5dbb2e352980771b91cc8cd6a4c8a51a86e5c8d31a'
FILES=('meme_machine/runtime/robinhood/plane.py','meme_machine/runtime/storage.py')
HELPERS=('meme_machine/runtime/native_audit_retention.py',)
GUARDS=('tests/test_ea_performance_source_guard.py',
    'tests/test_operational_candidate_source_guard.py',
    'tests/test_pump_restore_source_guard.py','tests/test_robinhood_usd_valuation.py')
INNER=('tests/fixtures/ea_performance_source_delta.json',
    'tests/fixtures/operational_candidate_source_delta.json',
    'tests/fixtures/pump_restore_reference_source_delta.json')
PROOF_INPUTS=('engineering/diagnostics/build_native_audit_source_proof.py',
    'engineering/diagnostics/native_audit_source_guard.template.txt')
OLD_IMPLEMENTATION='6eb8ab1ba1702224c1354c570db4f87aeb7b5ccd'


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def manifest(test):
    raw=MANIFEST.read_bytes()
    test.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256,
        'complete exact stable-audit successor proof')
    value=json.loads(raw)
    test.assertEqual(value['schema'],'authenticated-native-audit-source-delta-v1')
    test.assertEqual((value['base'],value['base_tree'],value['implementation'],value['implementation_tree']),
        (BASE,BASE_TREE,IMPLEMENTATION,IMPLEMENTATION_TREE))
    test.assertEqual(set(value['files']),set(FILES))
    test.assertEqual(set(value['helpers']),set(HELPERS))
    test.assertEqual(set(value['guards']),set(GUARDS))
    test.assertEqual(set(value['inner']),set(INNER))
    test.assertEqual(set(value['proof_inputs']),set(PROOF_INPUTS))
    for path,row in value['proof_inputs'].items():
        body=(ROOT/path).read_bytes()
        test.assertEqual((len(body),hashlib.sha256(body).hexdigest()),
            (row['bytes'],row['sha256']),path+':complete reproducible proof input')
    for path,row in value['helpers'].items():
        body=(ROOT/path).read_bytes()
        test.assertEqual((len(body),hashlib.sha256(body).hexdigest()),
            (row['bytes'],row['sha256']),path+':complete private helper, no exemption')
    return value


def _inverse(test,path,current,row):
    text=type(current) is str
    test.assertIn(type(current),(bytes,str))
    body=current.encode() if text else current
    checksum=hashlib.sha256(body).hexdigest()
    if checksum==row['before_sha256']:
        test.assertEqual(len(body),row['before_bytes']);return current
    test.assertEqual((len(body),checksum),(row['after_bytes'],row['after_sha256']),
        path+':complete exact stable-audit source')
    restored=body
    for hunk in row['changes']:
        before,after=(hunk[key].encode() for key in ('before','after'))
        test.assertTrue(after);test.assertEqual(restored.count(after),1)
        restored=restored.replace(after,before,1)
    test.assertEqual((len(restored),hashlib.sha256(restored).hexdigest()),
        (row['before_bytes'],row['before_sha256']))
    from tests.test_robinhood_usd_valuation import rally_delta
    test.assertEqual(rally_delta(restored,body),{key:row[key] for key in ('nodes','layouts')})
    return restored.decode() if text else restored


def audit_predecessor(test,path,current):
    """Only fixed complete active sources/read hooks precede old guard inputs."""
    current=capacity_predecessor(test,path,current)
    if path not in FILES+GUARDS:return current
    value=manifest(test)
    return _inverse(test,path,current,(value['files']|value['guards'])[path])


def active_runtime(test):
    """The actual current runtime must match this complete frozen successor."""
    value=manifest(test)
    expected={'M\t'+path for path in FILES}|{'A\t'+path for path in HELPERS}
    test.assertEqual(set(git('diff','--name-status',BASE,IMPLEMENTATION,'--','meme_machine').decode().splitlines()),expected)
    test.assertEqual(git('rev-parse',BASE+'^{tree}').decode().strip(),BASE_TREE)
    test.assertEqual(git('rev-parse',IMPLEMENTATION+'^{tree}').decode().strip(),IMPLEMENTATION_TREE)
    test.assertEqual(capacity_active_delta(test,git('diff','--name-only',IMPLEMENTATION,'--','meme_machine'),IMPLEMENTATION),b'',
        'all actual current runtime bytes match the exact complete successor')
    for options in ((),('--ignored',)):
        extra=git('ls-files','--others',*options,'--exclude-standard','--','meme_machine').decode().splitlines()
        test.assertEqual([path for path in extra if '__pycache__' not in Path(path).parts
            and not path.endswith('.pyc')],[])
    for path,row in value['files'].items():
        body=(ROOT/path).read_bytes()
        test.assertEqual(body,git('show',IMPLEMENTATION+':'+path))
        test.assertEqual(audit_predecessor(test,path,body),git('show',BASE+':'+path))
    for path,row in value['helpers'].items():
        test.assertEqual((ROOT/path).read_bytes(),git('show',IMPLEMENTATION+':'+path))
        test.assertEqual(row['imports'],imports((ROOT/path).read_bytes()))
    for path,row in value['guards'].items():
        body=(ROOT/path).read_bytes()
        test.assertEqual(hashlib.sha256(body).hexdigest(),row['after_sha256'])
        test.assertEqual(audit_predecessor(test,path,body),git('show',BASE+':'+path))
    return value


def audit_predecessor_runtime_delta(test,actual_delta):
    """Check CURRENT source, then query the genuine immutable predecessor cut.

    No Git result is mocked or fabricated.  The supplied real active delta must
    be exactly the files whose whole bytes reverse above plus the pinned added
    helper.  The old guard then checks its original runtime via actual Git.
    """
    active_runtime(test)
    actual_delta=capacity_native_delta(test,actual_delta,OLD_IMPLEMENTATION)
    test.assertEqual(actual_delta,b''.join((path+'\n').encode() for path in sorted(FILES+HELPERS)))
    return git('diff','--name-only',OLD_IMPLEMENTATION,BASE,'--','meme_machine')


def imports(raw):
    return sorted(ast.dump(node) for node in ast.walk(ast.parse(raw))
        if isinstance(node,(ast.Import,ast.ImportFrom)))


def read_hooks(raw):
    result=[]
    def walk(node,owner):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            owner=owner+'/'+node.name
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in (
                'audit_predecessor','audit_predecessor_runtime_delta'):
            result.append(dict(caller=owner,call=ast.dump(node)))
        for child in ast.iter_child_nodes(node):walk(child,owner)
    walk(ast.parse(raw),'module')
    return sorted(result,key=lambda row:(row['caller'],row['call']))


class NativeAuditSourceGuardTests(unittest.TestCase):
    def test_complete_frozen_and_actual_runtime_is_explicitly_authenticated(self):
        value=active_runtime(self)
        for path,row in value['files'].items():
            body=(ROOT/path).read_bytes();before=git('show',BASE+':'+path)
            self.assertEqual(audit_predecessor(self,path,body),before)
            self.assertEqual(audit_predecessor(self,path,before),before)
            self.assertEqual(audit_predecessor(self,path,body.decode()),before.decode())
        declaration="'tests.test_native_audit_source_guard',"
        for path in ('operational/tests.py','.github/workflows/ci.yml'):
            self.assertEqual((ROOT/path).read_text().count(declaration),1)

    def test_old_whole_guards_and_every_inner_proof_are_preserved(self):
        value=manifest(self)
        for path,row in value['guards'].items():
            body=(ROOT/path).read_bytes()
            self.assertEqual(read_hooks(body),row['fixed_read_hooks'])
            self.assertEqual(audit_predecessor(self,path,body),git('show',BASE+':'+path))
            for bad in (body+b'\n# unknown guard\n',body.replace(b'assertEqual',b'assertNotEqual',1)):
                with self.subTest(path=path),self.assertRaises(AssertionError):
                    audit_predecessor(self,path,bad)
        for path,row in value['inner'].items():
            body=(ROOT/path).read_bytes()
            self.assertEqual(body,git('show',BASE+':'+path))
            self.assertEqual((len(body),hashlib.sha256(body).hexdigest()),(row['bytes'],row['sha256']))

    def test_partial_unknown_crossed_source_and_helper_changes_refuse(self):
        value=manifest(self)
        for path,row in value['files'].items():
            body=(ROOT/path).read_bytes();changed=[b'',body+b'\n# unknown runtime\n']
            for hunk in row['changes']:
                partial=body.replace(hunk['after'].encode(),hunk['before'].encode(),1)
                if hashlib.sha256(partial).hexdigest()!=row['before_sha256']:changed.append(partial)
            for bad in changed:
                with self.subTest(path=path),self.assertRaises(AssertionError):audit_predecessor(self,path,bad)
            for other in FILES+HELPERS:
                if other!=path:
                    with self.subTest(path=path,other=other),self.assertRaises(AssertionError):
                        audit_predecessor(self,path,(ROOT/other).read_bytes())
        read=Path.read_bytes
        for path in HELPERS:
            body=(ROOT/path).read_bytes()
            for bad in (b'',body+b'\n# unknown private helper\n'):
                with patch.object(Path,'read_bytes',new=lambda p,bad=bad:bad if p==ROOT/path else read(p)),\
                        self.assertRaises(AssertionError):manifest(self)

    def test_complete_actual_checkout_census_rejects_changed_added_deleted_and_ignored(self):
        original=git
        commands=[(('diff','--name-status',BASE,IMPLEMENTATION,'--','meme_machine'),b'D\t'+FILES[0].encode()+b'\n'),
            (('diff','--name-only',IMPLEMENTATION,'--','meme_machine'),FILES[0].encode()+b'\n'),
            (('ls-files','--others','--exclude-standard','--','meme_machine'),b'meme_machine/unlisted.py\n'),
            (('ls-files','--others','--ignored','--exclude-standard','--','meme_machine'),b'meme_machine/unlisted.json\n')]
        for command,reply in commands:
            def supplied(*args):return reply if args==command else original(*args)
            with self.subTest(command=command),patch(__name__+'.git',side_effect=supplied),\
                    self.assertRaises(AssertionError):active_runtime(self)

    def test_source_view_cannot_erase_unknown_active_paths_or_manifest_mutations(self):
        expected=b''.join((path+'\n').encode() for path in sorted(FILES+HELPERS))
        self.assertEqual(audit_predecessor_runtime_delta(self,expected),
            git('diff','--name-only',OLD_IMPLEMENTATION,BASE,'--','meme_machine'))
        for bad in (b'',expected+b'meme_machine/unlisted.py\n',FILES[0].encode()+b'\n'):
            with self.assertRaises(AssertionError):audit_predecessor_runtime_delta(self,bad)
        raw=MANIFEST.read_bytes();read=Path.read_bytes
        for bad in (raw+b'\n',b'{}',raw.replace(BASE.encode(),b'f'*40,1)):
            with patch.object(Path,'read_bytes',new=lambda p,bad=bad:bad if p==MANIFEST else read(p)),\
                    self.assertRaises(AssertionError):manifest(self)
        self.assertEqual(audit_predecessor(self,'unrelated/source.py',b'unchanged'),b'unchanged')
