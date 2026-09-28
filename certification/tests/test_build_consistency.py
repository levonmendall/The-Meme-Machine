"""The identity generator cannot bless arbitrary code or strategy changes."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from certification.build_consistency import reviewed_delta,indexed_files,refresh_composed_hashes


class BuildConsistencyTests(unittest.TestCase):
    def test_operational_overlay_pins_do_not_expand_strategy_hash_contract(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rel='meme_machine/solana_checkpoint.py'
            (root/rel).parent.mkdir();(root/rel).write_text('reviewed=True\n')
            row=dict(composed_file_hashes={'strategy.py':'approved',rel:'old-generated'},
                     integration_overlay_files=[rel])
            old=dict(composed_file_hashes={'strategy.py':'approved'})
            refresh_composed_hashes(row,old,root)
            self.assertEqual(row['composed_file_hashes'],{'strategy.py':'approved'})
            old['composed_file_hashes'][rel]='prior-explicit-pin'
            refresh_composed_hashes(row,old,root)
            self.assertEqual(row['composed_file_hashes'][rel],hashlib.sha256((root/rel).read_bytes()).hexdigest())

    def test_fast_preflight_reuses_strict_downstream_strategy_contracts(self):
        from copy import deepcopy
        from certification.run import manifest
        from certification.directional_acceptance import policy_contract_checks
        spec=manifest()
        self.assertTrue(all(policy_contract_checks(spec).values()))
        for field in ('policy_hash','execution_sha'):
            changed=deepcopy(spec);changed['lanes']['meteora'][field]='changed'
            self.assertFalse(policy_contract_checks(changed)['meteora_threshold_revision_bounded'])
        changed=deepcopy(spec)
        changed['lanes']['meteora']['composed_file_hashes']['unexpected.py']='a'*64
        self.assertFalse(policy_contract_checks(changed)['meteora_threshold_revision_bounded'])

    def test_native_collection_rejects_missing_helper_without_running_test_body(self):
        from certification.build_consistency import native_test_collection
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);tests=root/'tests';tests.mkdir()
            (tests/'__init__.py').write_text('')
            (tests/'test_dependency.py').write_text(
                'import unittest\nfrom tests.required_fixture import VALUE\n'
                'class Case(unittest.TestCase):\n'
                ' def test_not_executed(self):\n'
                '  raise AssertionError("collection must not execute tests")\n')
            failed=native_test_collection(root,'pump')
            self.assertFalse(failed['passed'])
            self.assertIn('required_fixture',' '.join(failed['import_errors']))
            (tests/'required_fixture.py').write_text('VALUE=1\n')
            good=native_test_collection(root,'pump')
            self.assertTrue(good['passed'],good)
            self.assertEqual(good['collected_tests'],1)
            self.assertEqual(good['tests_executed'],0)

    def test_empty_native_collection_and_external_import_are_rejected(self):
        from certification.build_consistency import native_test_collection
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);tests=root/'tests';tests.mkdir()
            (tests/'__init__.py').write_text('')
            self.assertFalse(native_test_collection(root,'pump')['passed'])
            (tests/'test_external.py').write_text(
                'import socket\n'
                'socket.socket().connect(("192.0.2.1",443))\n')
            row=native_test_collection(root,'pump')
            self.assertFalse(row['passed'])
            self.assertTrue(row['external_socket_attempts'])

    def test_only_reviewed_operational_delta_is_accepted(self):
        before={'strategy.py':('100644','a'),'storage.py':('100644','b')}
        after=dict(before,**{'storage.py':('100644','c')})
        self.assertEqual(reviewed_delta(before,after,{'storage.py'}),['storage.py'])
        after['strategy.py']=('100644','d')
        with self.assertRaisesRegex(ValueError,'build_unreviewed_native_delta'):
            reviewed_delta(before,after,{'storage.py'})

    def test_removal_and_symlink_cannot_be_hash_rebound(self):
        before={'storage.py':('100644','a')}
        for after in ({},{'storage.py':('120000','b')}):
            with self.assertRaisesRegex(ValueError,'build_invalid_native_file'):
                reviewed_delta(before,after,{'storage.py'})

    def test_real_git_index_rejects_unstaged_and_ignored_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            subprocess.run(['git','init','-q',td],check=True)
            (root/'storage.py').write_text('a=1\n')
            subprocess.run(['git','add','storage.py'],cwd=td,check=True)
            self.assertIn('storage.py',indexed_files(root))
            (root/'storage.py').write_text('a=2\n')
            with self.assertRaisesRegex(ValueError,'build_unstaged_native_source'):indexed_files(root)
            subprocess.run(['git','add','storage.py'],cwd=td,check=True)
            (root/'.gitignore').write_text('shadow.py\n')
            (root/'shadow.py').write_text('malicious=True\n')
            with self.assertRaisesRegex(ValueError,'build_untracked_native_source'):indexed_files(root)


if __name__=='__main__':unittest.main()
