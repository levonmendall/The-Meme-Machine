"""Exact Pump restoration layer; all previous economic/source guards still run."""
from tests.test_native_audit_source_guard import audit_predecessor, audit_predecessor_runtime_delta
from tests.test_ea_performance_source_guard import performance_source, performance_guard_source
import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'tests/fixtures/pump_restore_reference_source_delta.json'
MANIFEST_SHA256='c9d5139401a5fb5b06bdd019ff796abefd1375dd2278e89a55741ae285e971a8'
BASE='d32153c9fd1a62e13650015a3edd375698bb41d4'
IMPLEMENTATION='5a2eaafd45bf955adcbd8a1f56a04dfa41ba5644'
IMPLEMENTATION_TREE='0c5e7673ecf403e0d1c89e767650ac1efe009cb4'
PATHS=('meme_machine/lanes/pump/runner.py','meme_machine/runtime/candidate_history.py',
       'meme_machine/solana_evidence_storage.py')
HELPER='meme_machine/runtime/candidate_restore_reads.py'


def manifest(test):
    raw=MANIFEST.read_bytes()
    test.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256,
        'exact reviewed Pump restoration manifest')
    value=json.loads(raw)
    test.assertEqual(value['schema'],'authenticated-pump-restoration-reference-source-delta-v1')
    test.assertEqual((value['base'],value['implementation'],value['implementation_tree']),
        (BASE,IMPLEMENTATION,IMPLEMENTATION_TREE))
    test.assertEqual(set(value['files']),set(PATHS))
    test.assertEqual(set(value['added_sources']),{HELPER})
    return value


def authenticated_helper(test,value):
    from tests.test_operational_candidate_source_guard import candidate_source_predecessor
    body=candidate_source_predecessor(test,HELPER,performance_source(test,HELPER,audit_predecessor(test,HELPER,(ROOT/HELPER).read_bytes())));record=value['added_sources'][HELPER]
    test.assertEqual(len(body),record['bytes'],'complete restoration helper length')
    test.assertEqual(hashlib.sha256(body).hexdigest(),record['sha256'],
        'complete restoration helper source, not an infrastructure exemption')


def pump_restore_predecessor(test,relative,current):
    """Reverse complete reviewed sources before the unchanged historical chain.

    This entry is used only for active-source reads. Original predecessor
    functions still process their older intermediate bytes and negative cases
    without any new normalization or permissive fallback.
    """
    from tests.test_operational_candidate_source_guard import candidate_source_predecessor
    current=candidate_source_predecessor(test,relative,current)
    if relative not in PATHS:return current
    value=manifest(test);authenticated_helper(test,value)
    if isinstance(current,str):current=current.encode()
    record=value['files'][relative]
    checksum=hashlib.sha256(current).hexdigest()
    if checksum==record['before_sha256']:return current
    test.assertEqual(checksum,record['after_sha256'],relative+':complete reviewed restoration successor')
    restored=current
    for change in record['changes']:
        before,after=(change[key].encode() for key in ('before','after'))
        test.assertTrue(after,relative+':explicit reversible source addition/replacement')
        test.assertEqual(restored.count(after),1,relative+':one exact restoration delta')
        restored=restored.replace(after,before,1)
    test.assertEqual(hashlib.sha256(restored).hexdigest(),record['before_sha256'],
        relative+':every original source byte restored')
    # Reuse the existing exact statement/method/header/order comparison. Its
    # original implementation is itself preserved by the legacy-file check.
    from tests.test_robinhood_usd_valuation import rally_delta
    test.assertEqual(rally_delta(restored,current),
        {key:record[key] for key in ('nodes','layouts')},relative+':exact named nodes and ordering')
    return restored


class PumpRestoreSourceGuardTests(unittest.TestCase):
    def test_all_three_complete_sources_and_added_helper_are_exactly_authenticated(self):
        value=manifest(self);authenticated_helper(self,value)
        for relative,record in value['files'].items():
            current=(ROOT/relative).read_bytes()
            with self.subTest(relative=relative):
                self.assertEqual(hashlib.sha256(current).hexdigest(),record['after_sha256'])
                previous=pump_restore_predecessor(self,relative,current)
                self.assertEqual(hashlib.sha256(previous).hexdigest(),record['before_sha256'])
                self.assertEqual(pump_restore_predecessor(self,relative,previous),previous)

    def test_legacy_guard_file_reverses_only_ten_active_reads_and_one_import(self):
        row=manifest(self)['legacy_guard'];current=performance_guard_source(self,row['path'],audit_predecessor(self,row['path'],(ROOT/row['path']).read_bytes()))
        from tests.test_operational_candidate_source_guard import original_guard_source
        current=original_guard_source(self,row['path'],current)
        import_line=b'from tests.test_pump_restore_source_guard import pump_restore_predecessor\n'
        self.assertEqual(current.count(import_line),1)
        restored=current.replace(import_line,b'',1);count=0
        for owner,relative,expected in (('test','relative',1),('self','path',1),('self','relative',8)):
            original='(ROOT/'+relative+').read_bytes()'
            wrapped=('pump_restore_predecessor('+owner+','+relative+','+original+')').encode()
            self.assertEqual(restored.count(wrapped),expected)
            count+=expected;restored=restored.replace(wrapped,original.encode())
        self.assertEqual(count,row['source_read_wrappers'])
        self.assertEqual(hashlib.sha256(restored).hexdigest(),row['before_sha256'],
            'every original constant, assertion, predecessor and mutation remains byte identical')

    def test_only_declared_restoration_and_codec_nodes_change(self):
        rows=manifest(self)['files']
        self.assertEqual(set(rows[PATHS[0]]['nodes']),
            {'module/FunctionDef:_restore_observed_pump_candidates'})
        self.assertEqual(set(rows[PATHS[1]]['nodes']),{
            'module/ClassDef:CandidateHistory/FunctionDef:'+name
            for name in ('_reference_body','events','restoration_reader')})
        codec=rows[PATHS[2]]['nodes']
        allowed={'module/ImportFrom:0:dataclasses','module/FunctionDef:decode',
            'module/FunctionDef:prepare_decode','module/FunctionDef:finish_decode',
            'module/ClassDef:_PreparedDecode'}
        self.assertEqual({key for key in codec if not key.startswith('module/ClassDef:_PreparedDecode/')},allowed)
        # The unchanged whole-file predecessor includes the original writer,
        # encoder, chunk hash/size limits, archive publication and retirement.
        codec_before=pump_restore_predecessor(self,PATHS[2],(ROOT/PATHS[2]).read_bytes())
        functions={node.name for node in ast.parse(codec_before).body if isinstance(node,ast.FunctionDef)}
        self.assertIn('decode',functions)
        self.assertNotIn('prepare_decode',functions);self.assertNotIn('finish_decode',functions)

    def test_partial_reversal_added_source_and_unreviewed_bytes_never_pass(self):
        for relative,record in manifest(self)['files'].items():
            current=(ROOT/relative).read_bytes()
            changes=[current+b'\n# unreviewed change\n',b'']
            for change in record['changes']:
                after=change['after'].encode();self.assertEqual(current.count(after),1)
                changes.append(current.replace(after,change['before'].encode(),1))
            for changed in changes:
                self.assertNotEqual(changed,current)
                with self.subTest(relative=relative,sha256=hashlib.sha256(changed).hexdigest()),\
                        self.assertRaises(AssertionError):
                    pump_restore_predecessor(self,relative,changed)

    def test_integrity_cancellation_default_economics_and_codec_mutations_are_refused(self):
        mutations={
            PATHS[0]:((b'cancelled=requested.is_set',b'cancelled=lambda:False'),
                (b'_restore_reference_reader=reads',b'_restore_reference_reader=None'),
                (b'archives.clear()',b'pass'),(b'reads.close()',b'pass'),
                (b'if mint in created:continue',b'if True:continue')),
            PATHS[1]:((b'path=self._reference_path(ref[\'path\'])',b'path=Path(ref[\'path\'])'),
                (b'if digest(ref)!=checksum:',b'if False:'),
                (b"r.get('identity')!=ref['canonical_identity']",b'False'),
                (b"checksum!=row[1] or row[1]!=ref['canonical_hash']",b'False'),
                (b'cancelled is not _restore_reference_reader.cancelled',b'False'),
                (b'r=deepcopy(r)',b'r=r')),
            PATHS[2]:((b'return finish_decode(prepare_decode(raw),db,chunks=chunks,decoded_chunks=decoded_chunks)',
                b'return {}'),(b"b'SEP1'",b"b'SEP2'"),
                (b"('meta','logMessages')",b"('meta','otherLogs')")),
        }
        for relative,pairs in mutations.items():
            current=(ROOT/relative).read_bytes()
            for before,after in pairs:
                self.assertIn(before,current)
                with self.subTest(relative=relative,before=before),self.assertRaises(AssertionError):
                    pump_restore_predecessor(self,relative,current.replace(before,after,1))

    def test_complete_helper_pin_refuses_any_budget_path_hash_or_owner_mutation(self):
        current=performance_source(self,HELPER,audit_predecessor(self,HELPER,(ROOT/HELPER).read_bytes()));read=Path.read_bytes
        changes=[current+b'\n# unreviewed helper\n',b'']
        for before,after in ((b'PAGE_REFERENCES = 128',b'PAGE_REFERENCES = 129'),
                (b'SNAPSHOT_SECONDS = .025',b'SNAPSHOT_SECONDS = 1'),
                (b"'?mode=ro'",b"'?mode=rw'"),
                (b'digest(ref) != checksum',b'False'),
                (b'threading.get_native_id() != self.thread',b'False')):
            self.assertIn(before,current);changes.append(current.replace(before,after,1))
        for changed in changes:
            with self.subTest(sha256=hashlib.sha256(changed).hexdigest()),\
                    patch.object(Path,'read_bytes',new=lambda path:changed if path==ROOT/HELPER else read(path)),\
                    self.assertRaises(AssertionError):
                pump_restore_predecessor(self,PATHS[0],(ROOT/PATHS[0]).read_bytes())

    def test_manifest_mutations_and_unknown_source_are_not_new_exemptions(self):
        original=MANIFEST.read_bytes();read=Path.read_bytes
        for changed in (original+b'\n',b'{}',original.replace(BASE.encode(),b'f'*40,1)):
            with self.subTest(sha256=hashlib.sha256(changed).hexdigest()),\
                    patch.object(Path,'read_bytes',new=lambda path:changed if path==MANIFEST else read(path)),\
                    self.assertRaises(AssertionError):
                pump_restore_predecessor(self,PATHS[0],(ROOT/PATHS[0]).read_bytes())
        self.assertEqual(pump_restore_predecessor(self,'unrelated/source.py',b'unchanged'),b'unchanged')
